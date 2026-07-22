# Tree of Thoughts — Phase 1: Exploration
## Problem: Caching Strategy for Social Media Feed API (100M users, 10K posts/sec)

---

## 1. Problem Breakdown

### Read Patterns
- **Volume**: Extremely high. 100M users reading feeds multiple times per day implies billions of feed requests daily.
- **Access pattern**: Highly skewed. A small percentage of users generate most reads (power-law distribution).
- **Payload**: Each feed read returns a paginated list of post references/IDs (typically 20-50 items per page).
- **Latency expectation**: Sub-100ms for cache hits; users expect near-instant feed loads.

### Write Patterns
- **Post ingestion**: 10,000 posts/second globally.
- **Fan-out multiplier**: Each post must reach N followers. If average follow count is 200, that's 2M follower-feed updates/sec in a naive push model.
- **Unfollow events**: Must invalidate or filter out posts from the unfollowed user. Frequency is lower than reads/writes but consistency-critical.
- **Post deletions/edits**: Less frequent but require cache coherence.

### Consistency Needs
- **Latency SLA**: New posts visible within 5 minutes. This allows eventual consistency; strong consistency is not required.
- **Invalidation correctness**: When a user unfollows, the cached feed must not show new posts from that user. Historical posts may remain (soft-filter) or be removed (hard-invalidated) depending on product choice.
- **Ordering**: Feeds are typically reverse-chronological or algorithmically scored. Cache must preserve sort order.

---

## 2. Solution Space Map

The major dimensions where solutions diverge:

| Dimension | Axis A | Axis B | Axis C |
|---|---|---|---|
| **Fan-out timing** | Push (at write) | Pull (at read) | Hybrid (selective push/pull) |
| **Cache topology** | Per-user feed cache | Shared post cache | Tiered (edge + origin) |
| **Invalidation model** | Explicit (event-driven) | TTL-based (lazy expiry) | Versioned (stamp-based) |
| **Storage backend** | In-memory (Redis) | Persistent KV | Mixed (hot in memory, warm on disk) |
| **Celebrity handling** | Same as normal users | Special path (no fan-out) | Ranked tiers |
| **Consistency guarantee** | Eventual (best-effort) | Causal (vector clocks) | Bounded staleness |

Our three approaches explore **orthogonal quadrants** of this space:
- **Approach 1**: Push + Per-user feed cache + Explicit invalidation + Redis
- **Approach 2**: Pull + Shared post cache + TTL/versioned + Mixed storage
- **Approach 3**: Hybrid + Tiered cache + Event sourcing + Ranked user tiers

---

## 3. Approach A: Push-Based Pre-Materialized Feeds

> **One-sentence summary**: Every new post is immediately pushed into each follower's pre-sorted feed cache; reads are pure cache lookups with no computation.

### Detailed Description

In this model, the system maintains a **dedicated, pre-computed feed cache per user**. When a user creates a post, an async fan-out worker reads the author's follower list and pushes the post ID (plus metadata) into each follower's feed cache—typically implemented as a Redis Sorted Set keyed by `(user_id, feed_type)` with the post timestamp as the score. Feed reads become O(log N) range queries on the sorted set: the API simply fetches the top-K post IDs from the user's cache, resolves full post payloads from a secondary post cache, and returns them.

Unfollow events trigger **targeted invalidation**: a background worker scans the unfollower's feed cache and removes all post IDs authored by the unfollowed user. Alternatively, a softer approach maintains a "blocked authors" filter set per user; at read time, post IDs from blocked authors are skipped. This trades read-time filtering for reduced invalidation churn. To handle the 5-minute freshness SLA, the fan-out pipeline uses a message queue (Kafka/RabbitMQ) with at-least-once delivery; posts are typically in follower caches within seconds.

### Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| **Redis Sorted Sets for feeds** | Native support for ordered collections, efficient range queries (ZRANGEBYSCORE), and O(log N) insertion. Widely battle-tested at scale (Twitter, Weibo). |
| **Async fan-out via message queue** | Decouples post-acceptance from feed distribution; allows backpressure handling and retry on follower-cache unavailability. |
| **Store only post IDs in feed cache** | Keeps feed cache memory-efficient. Full post payloads (text, images, engagement counts) are fetched in batch from a separate post cache, enabling independent TTL and eviction policies. |
| **Explicit invalidation on unfollow** | Product requirement mandates unfollowed content disappears. A blocked-authors filter + read-time skip is cheaper but may violate strict interpretations of the requirement. |
| **Single feed cache key per user** | Maximizes cache hit ratio: one key lookup serves the entire first page of the feed. >95% hit ratio achievable with appropriate cluster sizing and TTL. |

### Trade-offs

| Gains | Sacrifices |
|---|---|
| **O(1) reads**: Feed retrieval is a simple cache lookup + batch post fetch. Extremely low and predictable read latency. | **Write amplification**: 10K posts/sec × avg 200 followers = 2M writes/sec to feed caches. Requires massive write capacity. |
| **Predictable performance**: Read latency is independent of follow count or posting frequency. | **Hotspot risk**: Celebrity users with millions of followers create thundering-herd writes. Requires special handling or rate-limiting. |
| **Simple mental model**: Engineers understand "my feed is a mailbox." | **Storage cost**: 100M users × ~1,000 posts/feed × 8 bytes/post ID = ~800GB of feed index data minimum, plus replication. |
| **Easy pagination**: Cursor-based pagination is natively supported by sorted set ranges. | **Invalidation complexity**: Unfollowing requires scanning and mutating a potentially large sorted set. |

### Probability of Success
**0.75**

This is the most proven approach in production (Twitter historically, Weibo, etc.). The main risk is write-path scalability for high-follower users, but this is a well-understood problem with known mitigations (e.g., capping fan-out for celebrities, batched writes). The 95% cache hit ratio is straightforward because the feed is fully materialized in cache.

### Complexity
**Medium** — The read path is trivial, but the write path requires reliable message queues, idempotent fan-out workers, and careful handling of follow/unfollow edge cases.

### Potential Risks & Failure Modes

1. **Thundering herd on celebrity posts**: A user with 50M followers generates 50M cache writes. If not rate-limited or batched, this can overwhelm Redis cluster shards. Mitigation: cap fan-out for users above a follower threshold and switch those users to a pull/hybrid model.
2. **Message queue lag**: If fan-out workers fall behind, posts miss the 5-minute SLA. Mitigation: autoscaling workers, queue depth monitoring, and dead-letter queues for poison pills.
3. **Invalidation race conditions**: User unfollows while a fan-out for that author is in-flight. The new post may appear briefly. Mitigation: read-time author-filter check, or accept transient inconsistency given the 5-minute SLA allows eventual consistency.
4. **Redis hot-key contention**: Extremely popular users' feed keys may reside on a single Redis shard, creating CPU/network hotspots. Mitigation: Redis Cluster with rebalancing, or local caching of the first page at the API gateway.

---

## 4. Approach B: Pull-Based On-Read Aggregation

> **One-sentence summary**: No per-user feed cache exists; instead, individual posts and follow relationships are cached, and feeds are computed on-demand at read time by aggregating recent posts from all followees.

### Detailed Description

This model inverts the caching strategy: instead of caching the *result* (the feed), we cache the *inputs* (posts and follow graphs). Each post is stored once in a globally shared post cache keyed by `post_id`, with a TTL (e.g., 24–48 hours for recent posts). Each user's follow list is cached as a set of `followee_ids`. When a user requests their feed, the API layer: (1) fetches the cached follow list, (2) for each followee, queries their most recent N post IDs from an inverted index cache (e.g., `followee_id -> [recent_post_ids]`), (3) merges and sorts these post lists into a unified feed, and (4) fetches full post payloads in batch.

To meet the 95% cache hit ratio requirement, we aggressively cache both the follow lists and the per-author recent-post indices. The feed computation itself can be cached for a short TTL (e.g., 30–60 seconds) under a key like `(user_id, feed_cursor)` to amortize repeated identical requests. Unfollow events are trivial: simply update the follow list cache. Since there is no pre-materialized feed, no feed invalidation is needed—subsequent reads naturally exclude the unfollowed user.

### Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| **No per-user feed cache** | Eliminates write amplification entirely. 10K posts/sec remain 10K cache writes (to post storage + author index). |
| **Per-author recent-post index** | Each author has a small sorted set of their last ~100 post IDs. Followers query this index at read time. Storage per author is bounded and constant. |
| **Short-TTL feed result cache** | Caches the merged/sorted output of the aggregation for 30–60s. Handles the "user scrolling repeatedly" pattern and reduces redundant computation. |
| **Follow list as cached set** | Follow relationships change infrequently relative to reads. A single cached set per user with a long TTL (e.g., 1 hour) and explicit invalidation on follow/unfollow is highly efficient. |
| **Lazy expiry over explicit invalidation** | Post caches use TTL; no need to invalidate on unfollow. This dramatically simplifies the consistency model. |

### Trade-offs

| Gains | Sacrifices |
|---|---|
| **Zero write amplification**: Post ingestion does not scale with follower count. | **Read-time computation cost**: Feed reads require fetching M indices, merging, and sorting. Latency scales with follow count. |
| **Trivial unfollow handling**: Update one follow list; no feed scan needed. | **Variable read latency**: Users following 5,000 accounts pay a higher cost than users following 50. |
| **Lower total storage**: No 100M × N feed caches. Storage is O(posts) + O(users), not O(posts × followers). | **Complexity of aggregation engine**: Requires efficient multi-way merge of sorted streams (like a merge-join). |
| **Natural resilience to queue lag**: No fan-out pipeline to backpressure. Posts are visible as soon as they hit the post cache. | **Cache hit ratio challenge**: The 95% target is harder because feed reads hit multiple cache keys. One cold key (a followee's post index) degrades the entire request. |
| **Celebrity posts are free**: No special case for high-follower users. | **High p99 latency tail**: Merge-sorting 200 followee indices creates a long dependency chain. A single slow cache shard spikes latency. |

### Probability of Success
**0.55**

This approach is elegant for write scalability but struggles with the 95% cache hit ratio and sub-100ms latency requirements at scale. It works well for systems with lower read volumes or smaller follow graphs (e.g., Instagram's close-friends model). For a generic 100M-user social feed with unbounded follow counts, the read-path complexity and tail latency present significant engineering risk.

### Complexity
**High** — The read path requires a sophisticated aggregation engine, careful cache warming strategies, and robust handling of partial cache misses. The simplicity of writes is outweighed by the operational complexity of guaranteeing read performance.

### Potential Risks & Failure Modes

1. **Cache miss cascade**: If a follow list cache expires, the read path falls back to the database for followees, then fetches each followee's post index. A single feed read can generate 200+ DB/cache queries. Mitigation: follow-list cache must have near-100% hit ratio; use sticky caching or background refresh.
2. **Latency explosion with high follow counts**: Users following thousands of accounts trigger massive merge operations. Mitigation: cap the number of followees considered (e.g., top 500 by recency/engagement), or fall back to a push model for power users.
3. **Feed result cache staleness**: The 30-second result cache means a new post may not appear immediately, but this is well within the 5-minute SLA. Risk is acceptable.
4. **Hotspot on popular authors' post indices**: A celebrity's recent-post index is queried by millions of followers. Mitigation: replicate the index across cache shards, or serve it from a local in-process cache at the API layer.

---

## 5. Approach C: Hybrid Partitioned with Event Sourcing & Tiered Caches

> **One-sentence summary**: Users are partitioned by follower count into tiers—normal users get push-based pre-materialized feeds, celebrities get pull-based on-demand aggregation—and all changes are propagated through an event-sourced log with versioned cache entries for fast, consistent invalidation.

### Detailed Description

This approach rejects a one-size-fits-all model and instead **partitions users by their fan-out characteristics**. A user with <10K followers is a "normal user": their posts are pushed to follower feeds (Approach A). A user with >10K followers is a "celebrity": their posts are NOT fanned out; instead, follower feeds store a reference to the celebrity's timeline, which is aggregated at read time (Approach B). This partitioning solves the thundering-herd write problem while preserving fast reads for the vast majority of users.

Beneath this hybrid fan-out model lies an **event-sourced core**: all posts, follows, and unfollows are appended to an immutable event log (Kafka). Fan-out workers consume this log and write to cache. Crucially, cache entries are **versioned**: each user's feed cache entry carries a monotonic version number derived from the event log offset. When an unfollow occurs, the system emits an "unfollow" event; the fan-out worker increments the user's feed version and writes a new, filtered feed snapshot. Old versions are lazily evicted by TTL. This eliminates race conditions between fan-out and invalidation because the event log serializes all mutations.

The cache topology is **tiered**: a hot tier (Redis Cluster) stores the first 2 pages of each user's feed; a warm tier (e.g., ScyllaDB or DynamoDB) stores deeper pagination cursors and older post IDs; and an edge tier (CDN or regional cache) caches fully-rendered feed JSON for anonymous/non-personalized views. Read path: check edge → check hot Redis → check warm DB → compute fallback.

### Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| **Partition by follower count (10K threshold)** | The 99th percentile of users have few followers; pushing to them is cheap. The 1% with massive followings create write bottlenecks; pulling for them is optimal. |
| **Event sourcing as source of truth** | The event log provides an audit trail, enables replay for recovery, and serializes all mutations. Follow/unfollow and post creation are just different event types. |
| **Versioned cache entries** | Instead of mutating feed caches in place, writes produce new versions. This makes invalidation atomic and race-free: the version number is the invalidation mechanism. |
| **Tiered cache topology** | The hot/warm/edge split optimizes cost: Redis is expensive but fast for the critical first-page read; ScyllaDB is cheap for deep pagination; CDN handles anonymous traffic. |
| **CQRS separation** | Command path (posting, following) appends to the event log. Query path (feed reads) traverses the cache tiers. The two paths scale independently. |

### Trade-offs

| Gains | Sacrifices |
|---|---|
| **Optimal resource usage**: Normal users get fast O(1) reads; celebrities don't destroy write capacity. | **System complexity**: Must operate two fan-out models, an event log, versioned caches, and a tiered storage stack. |
| **Race-free invalidation**: Versioned entries eliminate unfollow fan-out races entirely. | **Operational overhead**: Event sourcing requires schema evolution discipline, log compaction, and replay infrastructure. |
| **Elastic read scaling**: Edge + hot tiers absorb massive read spikes. | **Cold-path latency**: If a user's feed is not in hot cache, fetching from warm DB + recomputing is slower than pure push. |
| **Strong auditability**: The event log is a complete history for debugging, compliance, and analytics. | **Engineering maturity required**: Event sourcing is a paradigm shift; team must understand log compaction, snapshotting, and offset management. |
| **Graceful degradation**: If Redis is overloaded, reads fall back to warm DB without data loss. | **Higher baseline latency for deep pages**: Page 3+ requires warm DB access, adding 5–20ms. |

### Probability of Success
**0.65**

This is the most "correct" architecture for a mature, large-scale system, but it carries the highest implementation risk. The hybrid model directly addresses the celebrity problem that makes pure push risky, and event sourcing provides a principled consistency foundation. However, the operational complexity of running Kafka, Redis Cluster, ScyllaDB, and versioned cache semantics in concert is significant. Success depends heavily on team expertise with event-sourced systems.

### Complexity
**High** — This is a composite architecture requiring expertise in stream processing, multi-tier caching, CQRS, and operational monitoring across at least three distinct storage systems.

### Potential Risks & Failure Modes

1. **Event log consumer lag**: If fan-out workers can't keep up with 10K posts/sec + follow/unfollow events, feeds stale beyond 5 minutes. Mitigation: partition the event log by author ID, scale consumer groups horizontally, and monitor consumer lag as a critical metric.
2. **Version proliferation in cache**: Each unfollow creates a new version. A user who rapidly follows/unfollows could generate version spam. Mitigation: debounce unfollow events, coalesce versions within a time window, or compact the event log.
3. **Threshold misconfiguration**: The 10K follower threshold may be wrong for the actual workload. Mitigation: make it dynamically adjustable per-user based on real-time write cost metrics.
4. **Warm tier saturation during cache warming**: If Redis suffers a mass eviction (e.g., restart), all reads hit ScyllaDB simultaneously. Mitigation: background warming jobs, circuit breakers, and rate-limited fallback.
5. **Event schema evolution**: A change to the post event format requires back-compat handling in all consumers. Mitigation: strict schema registry (Confluent/Protobuf), versioned event types, and integration testing against the event log.

---

## 6. Summary Comparison

| Dimension | Approach A: Push | Approach B: Pull | Approach C: Hybrid + Event Sourcing |
|---|---|---|---|
| **Fan-out model** | Push at write time | Pull at read time | Partitioned: push for normal, pull for celebrities |
| **Cache topology** | Per-user feed cache (Redis) | Shared post + author indices | Tiered: hot (Redis) + warm (ScyllaDB) + edge (CDN) |
| **Read latency** | Very low, predictable | Variable, follow-count dependent | Very low for page 1; moderate for deep pages |
| **Write amplification** | High (followers × posts) | None | Medium (only normal users fanned out) |
| **Unfollow handling** | Explicit invalidation/scan | Trivial (follow list update only) | Versioned feed snapshot via event log |
| **Cache hit ratio** | Easy >95% | Harder to guarantee | Easy >95% for hot tier |
| **Celebrity handling** | Risky / requires mitigation | Natural | First-class partitioned solution |
| **Consistency model** | Eventual, race-prone on unfollow | Stronger (no pre-computed state to race) | Causal via event log serialization |
| **Probability of success** | 0.75 | 0.55 | 0.65 |
| **Complexity** | Medium | High | High |
| **Best fit if...** | Follow counts are bounded; team wants proven pattern | Write volume dominates; follow graphs are small | System is long-lived; team has stream-processing expertise; cost optimization matters |
