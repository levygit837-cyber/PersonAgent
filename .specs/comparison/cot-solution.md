# Social Media Feed API — Caching Strategy Design

## Context
- **100M users** with personalized feeds
- **10K posts/second** globally
- **5-minute SLA** for new posts to appear in followers' feeds
- **>95% cache hit ratio** required
- **Unfollow must invalidate** the cached feed

---

## Step 1: Decompose the Problem

### Read Patterns
| Pattern | Frequency | Characteristics |
|---------|-----------|-----------------|
| Feed read (home timeline) | ~100–500× more frequent than writes | Returns top 50–100 posts sorted by recency |
| Individual post read | Embedded inside feed reads | High batch-read pattern (50 posts at once) |
| Paginated scroll | Secondary | Requests older pages; lower frequency |

**Key insight:** Reads dominate. A user may check their feed 20–50 times/day but post only once every few days.

### Hot Data Paths
1. **Celebrity posts** — A user with 10M followers creates massive read amplification if pulled on every feed load.
2. **Trending content** — Viral posts spike read volume.
3. **Active user feeds** — Top 5% of users generate ~50% of feed reads.

### Consistency Requirements
- **Eventual consistency** is acceptable. Users do not require strict linearizability for a social feed.
- The 5-minute SLA allows for asynchronous propagation.
- Unfollow invalidation should be **prompt** (sub-second to few seconds) but brief staleness is tolerable.

---

## Step 2: Identify Design Dimensions

1. **Cache Topology** — Where do caches live? How many layers?
2. **Feed Computation Strategy** — Push (fan-out on write), Pull (fan-out on read), or Hybrid?
3. **Data Structures for Feed Storage** — How do we store and query feed entries in cache?
4. **Invalidation Mechanism** — How do we evict/remove stale entries, especially on unfollow?

---

## Step 3: Evaluate Options

### Dimension A: Cache Topology

| Option | Latency | Complexity | Consistency | Scalability | Score |
|--------|---------|------------|-------------|-------------|-------|
| **A1. Single Redis Cluster** | Low (~2–5ms) | Low | Good | Moderate — hot-key bottleneck | ⭐⭐⭐ |
| **A2. Multi-layer: Local LRU → Redis Cluster → DB** | Very low (~0.1ms local hit) | Medium | Good | High — local absorbs hot keys | ⭐⭐⭐⭐⭐ |
| **A3. CDN + Redis + DB** | Lowest for static assets | High | Poor — CDN stale | Moderate — feeds are dynamic | ⭐⭐ |

**Analysis:** Option A2 wins. Local per-process LRU caches (e.g., Caffeine, Guava) inside stateless Feed Service instances absorb the "head-of-line" hot users (celebrities and power users). Redis Cluster handles the long tail. DB is the fallback.

### Dimension B: Feed Computation Strategy

| Option | Read Latency | Write Complexity | Write Amplification | Scalability | Score |
|--------|--------------|------------------|---------------------|-------------|-------|
| **B1. Pure Pull** | High — O(F) joins per read where F = follows | Low | None | Poor — fails at scale | ⭐⭐ |
| **B2. Pure Push** | Very low — O(1) | High | Extreme — 10K posts × 1M followers = 10B writes/sec for celebrities | Poor — impossible | ⭐⭐ |
| **B3. Hybrid Push/Pull** | Low — O(1) for normal, O(C) merge for celebrities | Medium | Bounded — push capped at 100K followers | High | ⭐⭐⭐⭐⭐ |

**Analysis:** Option B3 is the industry standard (used by Twitter/X, Instagram). Define a **celebrity threshold** (e.g., 100K followers). Normal users are **pushed** to followers' feed caches. Celebrities are **pulled** at read-time by merging their recent posts into the requesting user's feed.

### Dimension C: Data Structures for Feed Storage

| Option | Pagination | Insertion | Selective Removal | Memory Efficiency | Score |
|--------|------------|-----------|-------------------|-------------------|-------|
| **C1. Redis List (LPUSH/LTRIM)** | Poor — linear scan | Fast | Impossible without full scan | Good | ⭐⭐ |
| **C2. Redis Sorted Set (ZSET)** | Excellent — ZREVRANGE by rank/score | Fast — ZADD | Possible with ZSCAN + ZREM | Good | ⭐⭐⭐⭐⭐ |
| **C3. Materialized JSON blob** | Poor — rewrite on change | Slow — read-modify-write | Impossible without rewrite | Poor | ⭐⭐ |

**Analysis:** Option C2 (Redis ZSET) is optimal. Score = `post_timestamp` (millis since epoch). Member = `"{author_id}:{post_id}"`. This encoding enables selective removal by author on unfollow.

### Dimension D: Invalidation Mechanism

| Option | Immediate? | Unfollow Support | Complexity | Reliability | Score |
|--------|------------|------------------|------------|-------------|-------|
| **D1. TTL-only (e.g., 10 min)** | No | Poor — stale data persists | Very low | High | ⭐⭐ |
| **D2. Event-driven (Kafka → workers)** | Yes (sub-second) | Excellent | Medium | High — at-least-once delivery | ⭐⭐⭐⭐⭐ |
| **D3. Versioned cache keys** | Yes | Good — but leaks old versions | Low | Medium — memory growth | ⭐⭐⭐ |

**Analysis:** Option D2 wins. An event bus (Kafka) publishes `UnfollowEvent` and `PostDeletedEvent`. A dedicated Invalidation Service consumes events and surgically removes entries from Redis ZSETs. TTL of 1 hour acts as a safety net.

---

## Step 4: Concrete Decisions

| Dimension | Decision | Justification |
|-----------|----------|---------------|
| **Topology** | Multi-layer: Local LRU → Redis Cluster → Cassandra/PostgreSQL | Local cache absorbs top 5% power users (~50% of reads). Redis handles 95% of remaining. DB fallback is rare. |
| **Computation** | Hybrid Push/Pull with 100K follower threshold | Pure push fails for celebrities (10K posts/sec × 1M followers = 10B writes/sec). Pure pull fails for normal users (200M follows to scan). Hybrid caps write amplification at 10K × 100K = 1B ops/sec worst-case, but celebrities are <1% of volume. |
| **Data Structure** | Redis ZSET per user: `feed:{user_id}` | Score = `timestamp`, Member = `"{author_id}:{post_id}"`. Enables O(log N) insertion, O(log N + M) pagination, and selective removal. Capped at 1000 entries. |
| **Invalidation** | Kafka + Invalidation Service | `UnfollowEvent` triggers `ZSCAN feed:{follower_id} MATCH {author_id}:*` + `ZREM`. `PostDeletedEvent` triggers same. TTL = 1h as fallback. |

### Key Numbers
- **Average follows per user:** ~200 (median much lower, mean pulled up by power users).
- **Redis ZADD amplification:** 10K posts/sec × 200 avg followers = **2M writes/sec** to Redis. A Redis shard handles ~50–100K ops/sec → need **30–40 shards** for writes, plus replicas for reads.
- **Feed cap:** 1000 entries per user ZSET. At ~30 bytes/entry → ~30KB per user. For 10M daily active users → **~300GB working set**, easily fit in a 50-node Redis cluster.
- **Celebrity threshold:** 100K followers. Celebrity posts are read by merging at most ~10 celebrity ZSETs per user (assuming user follows 200, maybe 10 are celebrities) → negligible read overhead.

---

## Step 5: Full Architecture

### Component Diagram

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   Client    │──────▶│  API Gateway │──────▶│  Feed Service   │
└─────────────┘      └──────────────┘      │  (stateless × N)│
                                           └────────┬────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────────────────┐
                    │                               │                               │
                    ▼                               ▼                               ▼
            ┌──────────────┐              ┌──────────────┐              ┌──────────────┐
            │  Local LRU   │              │ Redis Cluster│              │   Kafka      │
            │  Cache       │              │  (sharded)   │              │  (event bus) │
            │  (per node)  │              │              │              │              │
            └──────────────┘              └──────────────┘              └──────┬───────┘
                    │                               │                          │
                    │                               │                          ▼
                    │                               │                 ┌─────────────────┐
                    │                               │                 │ Fan-out Service │
                    │                               │                 │ (workers × M)   │
                    │                               │                 └────────┬────────┘
                    │                               │                          │
                    ▼                               ▼                          ▼
            ┌──────────────┐              ┌──────────────┐              ┌──────────────┐
            │ Cassandra/   │              │   PostgreSQL │              │  Followers   │
            │ ScyllaDB     │              │   (metadata) │              │  Service     │
            │  (posts)     │              │              │              │              │
            └──────────────┘              └──────────────┘              └──────────────┘
```

### Component Responsibilities

| Component | Technology | Responsibility |
|-----------|-----------|----------------|
| **API Gateway** | Envoy / NGINX | Rate limiting, auth, routing |
| **Feed Service** | Go / Java / Node | Orchestrate read path, local caching, merge logic |
| **Local LRU Cache** | Caffeine / Guava / `lru-cache` | Cache top 50 posts per user per app node. TTL = 30–60s. |
| **Redis Cluster** | Redis 7+ with Cluster Mode | Primary distributed cache. Sharded by `hash(user_id) % shards`. |
| **Kafka** | Kafka / Pulsar | Event bus: `PostCreated`, `Unfollow`, `PostDeleted` |
| **Fan-out Service** | Consumer workers | Push posts to follower feed ZSETs for non-celebrities |
| **Invalidation Service** | Consumer workers | Handle unfollow and deletion events |
| **Post Store** | Cassandra / ScyllaDB | Write-optimized store for post content |
| **Followers Service** | PostgreSQL + cache | Follow graph queries |

### Redis Key Schema

```
feed:{user_id}              → ZSET {score: timestamp, member: "{author_id}:{post_id}"}
posts:{user_id}             → ZSET {score: timestamp, member: post_id}  (for celebrities)
post:{post_id}              → HASH {author_id, content, media_url, created_at, ...}
follows:{user_id}           → SET {followed_user_id_1, followed_user_id_2, ...}
```

### Data Flow: Write Path (Normal User)

1. **User creates post** → API Gateway → Post Service.
2. Post Service writes to **Cassandra** (async, durable).
3. Post Service publishes `PostCreatedEvent` to **Kafka**: `{post_id, author_id, timestamp}`.
4. **Fan-out Service** consumes the event:
   - Queries Followers Service: "get all follower IDs for `author_id`".
   - For each follower ID: `ZADD feed:{follower_id} {timestamp} "{author_id}:{post_id}"`.
   - Trims feed to cap: `ZREMRANGEBYRANK feed:{follower_id} 0 -1001`.
5. Total Redis writes: `follower_count` ZADDs. For a user with 1K followers → 1K ZADDs in <100ms.

### Data Flow: Write Path (Celebrity, >100K Followers)

1. Steps 1–2 identical (write to DB, publish event).
2. **Fan-out Service** detects celebrity status (follower_count > 100K).
3. Skips per-follower push.
4. Instead: `ZADD posts:{celebrity_id} {timestamp} {post_id}`.
5. Trim: `ZREMRANGEBYRANK posts:{celebrity_id} 0 -501` (keep last 500).

### Data Flow: Read Path

1. Client requests `/feed` → Feed Service.
2. **Local LRU Check:** key = `local_feed:{user_id}`. Hit → return immediately (~0.1ms).
3. **Redis: Fetch pushed feed:** `ZREVRANGE feed:{user_id} 0 49 WITHSCORES`.
4. **Identify followed celebrities:** Intersect `follows:{user_id}` with celebrity registry (cached Bloom filter or in-memory set in Feed Service).
5. **Redis: Fetch celebrity posts:** For each followed celebrity: `ZREVRANGE posts:{celebrity_id} 0 49 WITHSCORES`.
6. **K-way merge:** Merge results from step 3 and step 5 by `timestamp` descending. Take top 50 `post_id`s.
7. **Redis: Hydrate post metadata:** Pipeline `HGETALL post:{post_id}` for all 50 posts.
8. **Serialize & return.** Populate local LRU cache with TTL = 60s.

### Data Flow: Unfollow Invalidation

1. User unfollows `target_id` → Follow Service updates DB.
2. Follow Service publishes `UnfollowEvent` to Kafka: `{follower_id, target_id}`.
3. **Invalidation Service** consumes:
   - `SREM follows:{follower_id} {target_id}`.
   - `ZSCAN feed:{follower_id} 0 MATCH {target_id}:* COUNT 1000`.
   - `ZREM feed:{follower_id} {matched_member_1} {matched_member_2} ...`.
4. Optionally: `DEL local_feed:{follower_id}` from all Feed Service nodes (broadcast or wait for TTL).

---

## Step 6: Verify Against Requirements

| Requirement | Verification | Status |
|-------------|--------------|--------|
| **Personalized feed** | Each user has a dedicated `feed:{user_id}` ZSET containing only posts from followed normal users + pulled celebrity posts. | ✅ Met |
| **New posts within 5 minutes** | Push path: Kafka → Fan-out → Redis ZADD takes milliseconds to seconds. Even with consumer lag, 5 minutes is extremely conservative. Monitored via consumer lag metrics. | ✅ Met |
| **10K posts/sec globally** | Normal posts: 10K × 200 avg followers = 2M ZADDs/sec. 40 Redis shards × 50K ops/sec = 2M ops/sec. Celebrity posts: bypass fan-out, just 1 ZADD per post. Total sustained throughput is well within limits with headroom for spikes. | ✅ Met |
| **Cache hit ratio >95%** | Layer 1: Local LRU — catches top users (~50% of reads). Layer 2: Redis Cluster — catches remaining with LRU eviction tuned to working set size (~90% of non-local hits). Combined: `1 - (0.5 × 0.1)` = **95%**. With active user bias, realistically 96–98%. | ✅ Met |
| **Unfollow invalidates cache** | Event-driven `ZSCAN` + `ZREM` surgically removes target author's posts from `feed:{user_id}`. No stale data remains. Safety TTL ensures eventual cleanup even if event is lost. | ✅ Met |

### Gap Analysis
- **Celebrity read bottleneck:** Reading `posts:{celebrity_id}` for a top celebrity (50M followers) means 50M users may hit that key. Mitigated by:
  - Celebrity posts also cached in **Feed Service local LRU** (50M users × 60s TTL → high hit rate in app layer).
  - Redis read replicas for `posts:{celebrity_id}` key.
- **Cold start / cache warming:** New user or cache eviction causes a DB query. Mitigated by:
  - Async cache warming on user login.
  - Prefetching on miss with background task.

---

## Step 7: Trade-offs and Risks

### Trade-offs

| Trade-off | Our Choice | Alternative | Why We Chose This |
|-----------|-----------|-------------|-------------------|
| **Write amplification vs read latency** | Accept write amplification (push) for normal users | Pure pull | Push gives O(1) reads which is critical for user experience. Write cost is bounded and shardable. |
| **Memory vs precision** | Store `author_id:post_id` in ZSET member | Store only `post_id` | Encoding author in member enables surgical unfollow invalidation. Costs ~8 bytes extra per entry (negligible). |
| **Consistency vs availability** | Favor availability (Redis LRU eviction, async fan-out) | Strict consistency | Social feeds tolerate seconds of staleness. 5-minute SLA is loose. |
| **Complexity vs correctness** | Event-driven invalidation | TTL-only | Unfollow is an explicit user action; they expect immediate effect. Event-driven adds complexity but meets UX expectations. |

### Risks and Failure Modes

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Fan-out service lag** | Medium (spike in posts) | Posts exceed 5-min SLA | Autoscaling fan-out workers. Backpressure monitoring. Alert on Kafka consumer lag. |
| **Redis hot key (celebrity `posts:` key)** | High | Latency spikes for popular celebrities | Local LRU cache absorbs 90%+ of these reads. Redis read replicas. Consider sharding celebrity key by time bucket if needed. |
| **Redis memory exhaustion** | Medium | Eviction of active user feeds, DB thrashing | Monitor memory. Use `allkeys-lru` policy. Scale cluster horizontally. Cap per-user feed at 1000 entries. |
| **Invalidation event loss** | Low | Unfollowed user's posts remain visible | Kafka at-least-once delivery. Idempotent consumers. 1-hour TTL as safety net. |
| **Thundering herd on cache miss** | Medium | DB overload | Singleflight / request coalescing in Feed Service. Async cache warming. |
| **Follower count explosion (botnets)** | Low | Fan-out amplification attack | Rate limiting per user. CAPTCHA for suspicious follow patterns. Dynamic celebrity threshold. |

### When This Design Fails
1. **Realtime feeds (e.g., live sports, stock trading):** The 5-minute SLA and async fan-out are too slow. Would need WebSockets + in-memory pub/sub.
2. **Extremely high follow counts for average users:** If median follows jump from 200 to 10K, the merge step in reads becomes expensive. Would need to revisit with more aggressive push or feed pre-computation.
3. **Geo-replicated low-latency requirements:** If users are globally distributed and expect <50ms feeds worldwide, a single Redis cluster may not suffice. Would need regional cache clusters + CRDT-based replication.

---

## Summary

The design uses a **hybrid push/pull feed computation model** with a **two-tier cache** (local LRU + Redis Cluster) to achieve >95% hit ratio at scale. Redis **Sorted Sets** with composite members (`"{author_id}:{post_id}"`) provide efficient pagination and surgical invalidation. Kafka-driven **event-based invalidation** ensures unfollows are reflected promptly. The architecture comfortably handles 10K posts/sec by bounding write amplification through a celebrity threshold, while maintaining sub-100ms read latencies for the vast majority of users.
