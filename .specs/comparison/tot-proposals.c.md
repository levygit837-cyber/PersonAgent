# Tree of Thoughts — Phase 1: Exploration
## Problem: Caching Strategy for Social Media Feed API (100M Users, 10K posts/sec, <5min latency)

---

## 1. Problem Breakdown

### Read Patterns
- **Volume**: 100M users imply read QPS in the hundreds of thousands to millions range, assuming even moderate engagement.
- **Access pattern**: Highly skewed — top 1% of users drive ~50% of reads (power-law distribution). Long tail of inactive users generates negligible traffic.
- **Feed semantics**: Each feed is a time-ordered, personalized list of posts from followed accounts. Users typically read the top N items (e.g., first 20-50) and paginate infrequently.
- **Freshness expectation**: New posts must appear within 5 minutes, but sub-minute latency is preferred for active users.

### Write Patterns
- **Ingestion rate**: 10,000 posts/second globally.
- **Fan-out multiplier**: If the average user follows 200 accounts and the average user has 500 followers, each post potentially fans out to 500 feeds. This creates a fan-out of 10K × 500 = 5M feed mutations/second at peak if fully materialized.
- **Burstiness**: Traffic is not uniform; spikes occur during global events, celebrity posts, or coordinated activity.
- **Unfollow events**: Must trigger precise invalidation of the unfollower's cached feed.

### Consistency Needs
- **Eventual consistency is acceptable** for feed content (a post appearing at T+4min vs T+1min is fine).
- **Strong consistency is required** for unfollow invalidation (stale follow data is a privacy/UX bug).
- **Ordering**: Rough chronological order within a feed is sufficient; strict global ordering across all users is not required.

---

## 2. Solution Space Dimensions

Solutions to this problem vary primarily along the following axes:

| Dimension | Options |
|-----------|---------|
| **Fan-out Model** | Push (write-time fan-out) vs Pull (read-time assembly) vs Hybrid |
| **Feed Materialization** | Fully pre-computed per user vs On-demand query vs Partial (e.g., hot feeds only) |
| **Cache Topology** | Centralized Redis/Memcached vs Edge/CDN caching vs Tiered (edge → regional → origin) |
| **Invalidation Strategy** | Precise key-based invalidation vs TTL-based expiration vs Probabilistic early refresh |
| **Data Partitioning** | User-sharded (each user owns their feed) vs Post-sharded (each post owns its replicas) vs Hybrid |
| **Consistency Model** | Strong (immediate invalidate) vs Eventual (background propagate) vs Probabilistic |

The three approaches below explore distinct regions of this space.

---

## Approach 1: Pull-Based Fan-Out with Multi-Tier Cache

**One-sentence summary**: Feeds are assembled on-demand at read time by querying aggregated indices of recent posts, cached at edge, regional, and central layers.

### Detailed Description

In this architecture, no per-user feed is pre-materialized. Instead, each user maintains a lightweight "following list" (a set of user IDs they follow). When a user requests their feed, the system queries a time-ordered index of recent posts — partitioned by author — and merges the N most recent posts from all followed authors in real time. This merged result is then cached for a short TTL (e.g., 30-60 seconds) at multiple tiers: a CDN/edge cache for anonymous/unauthenticated landing-page traffic, a regional cache cluster for authenticated users, and a central cache for index shards.

The post index is the critical shared data structure. It can be implemented as a sharded, time-sorted structure (e.g., Redis Sorted Sets per author, or a wide-column store like Cassandra with time-range queries). Unfollow events are handled by simply updating the user's following list in a strongly consistent metadata store; subsequent feed reads will naturally exclude the unfollowed author's posts because the query references the updated following list. No explicit cache invalidation of feed content is needed — the TTL naturally expires stale merged results.

### Key Design Decisions and Rationale

- **Fan-out on read**: Avoids the write amplification nightmare of pushing 10K posts/sec to an average fan-out of 500 followers (5M mutations/sec). Instead, the cost is paid by the reader.
- **Multi-tier caching**: Edge/CDN caches handle unauthenticated or lightly personalized traffic (e.g., trending feeds). Regional caches handle authenticated feed reads with short TTLs. The central cache holds the post indices themselves.
- **Short TTL over precise invalidation**: Feed merges are cached for 30-60 seconds. This is acceptable because the 5-minute freshness requirement is loose; TTL expiration provides bounded staleness without complex invalidation logic.
- **Author-sharded post index**: Posts are indexed by author, not by follower. This keeps the write path simple (one index insertion per post) and makes the data model independent of follow graph size.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| O(1) write path per post (just index the post) | O(F) read path per feed, where F = number of followed authors |
| No write amplification; scales linearly with posts | High read latency for users with many follows (>1,000) |
| Simple unfollow semantics (just update a list) | Cache hit ratio relies on repeated reads from same user within TTL window |
| No complex invalidation logic | Feed assembly is CPU/memory intensive at read time |
| Natural resilience to celebrity-post spikes | Pagination beyond the first page becomes expensive |

- **Probability of success**: 0.75 — Proven pattern (early Twitter, Instagram). Works well for moderate fan-outs but degrades for power users.
- **Complexity**: Medium — Multiple cache tiers and a fast merge algorithm are required, but the data model is simple.
- **Potential risks and failure modes**:
  1. **Thundering herd on hot authors**: A celebrity with 50M followers will cause massive concurrent index reads. Mitigation: separate "super-user" handling (e.g., always-cache their recent posts in a hot set).
  2. **Read latency explosion for high-follow users**: Users following >1,000 accounts will experience slow merges. Mitigation: cap follows or switch to a hybrid model for such users.
  3. **Cache stampede at TTL expiry**: Many users' caches expiring simultaneously can overload the backend. Mitigation: probabilistic early refresh (refresh at TTL - random_offset).

---

## Approach 2: Push-Based Fan-Out with Fully Materialized Per-User Feeds

**One-sentence summary**: Every post is written into a pre-computed, per-user feed storage at publish time, making feed reads a simple O(1) cache lookup.

### Detailed Description

In this architecture, each user has a dedicated, pre-materialized feed stored in a fast key-value system (e.g., Redis list or stream per user ID). When a user creates a post, the system synchronously or asynchronously pushes the post ID into the materialized feeds of every follower. A feed read becomes a single `LRANGE` or equivalent operation against the user's feed key, returning the top N post IDs, which are then hydrated with full post metadata from a secondary cache.

Unfollow events trigger an explicit, targeted invalidation: the system scans the unfollowed author's recent posts and removes their entries from the unfollower's materialized feed. This operation is done via a background task or a message-queue worker to avoid blocking the unfollow API. To manage write amplification, the system enforces a maximum fan-out limit per post (e.g., 10,000 followers). Users with more followers are treated as "super-users" whose posts are not fully pushed but instead handled via a pull-based fallback or a separate hot-set cache.

### Key Design Decisions and Rationale

- **Fan-out on write**: Transforms the expensive O(F) read merge into a cheap O(1) cache lookup, delivering extremely low and predictable read latency.
- **Per-user materialized feed**: The feed is the source of truth for what a user sees. This enables complex ranking/sorting logic to be applied at write time if desired.
- **Hybrid super-user handling**: Without a fan-out cap, a celebrity post to 50M followers would generate 50M writes instantly, overwhelming the system. Capping fan-out and falling back to pull for the remainder keeps the write path bounded.
- **Explicit invalidation on unfollow**: Because feeds are pre-materialized, an unfollow must actively remove stale content. A background job consuming unfollow events from a message bus (Kafka, NATS) performs this cleanup.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| O(1) read latency — extremely fast, predictable feeds | Massive write amplification (up to capped fan-out per post) |
| >99% cache hit ratio (the entire feed is in one key) | Storage cost scales with users × feed depth, not just posts |
| No read-time merge complexity | Unfollow invalidation is complex and eventually consistent |
| Easy to add ranking/scoring at write time | Write path is complex, async, and failure-prone |
| Predictable performance regardless of follow count | Super-user fallback introduces dual-system complexity |

- **Probability of success**: 0.70 — This is the late-Twitter/X model. Highly effective at read scale but requires significant operational maturity to handle write-path backpressure and super-user edge cases.
- **Complexity**: High — Fan-out pipeline, dead-letter queues for failed pushes, super-user fallback, and invalidation workers all add operational burden.
- **Potential risks and failure modes**:
  1. **Write-path overload during viral events**: A major event can spike posts/sec and fan-out simultaneously. Mitigation: backpressure, rate limiting on fan-out workers, and graceful degradation to pull.
  2. **Invalidation lag after unfollow**: If the invalidation worker falls behind, users see posts from unfollowed accounts. Mitigation: prioritize unfollow events, set SLOs on invalidation latency (<5 seconds).
  3. **Storage explosion**: 100M users × 1,000 post IDs per feed = 100B entries. Mitigation: aggressive trimming (keep only top 500-1000 posts), archive old feeds to cold storage.
  4. **Hot-key contention on popular feeds**: A user's feed key in Redis can become a hot shard. Mitigation: hash tagging, read replicas, or feed sharding by time window.

---

## Approach 3: Hybrid with Regional Fan-Out and Probabilistic Cache Invalidation

**One-sentence summary**: A tiered system that pre-materializes feeds only for active users in regional caches, uses probabilistic invalidation for stale data, and falls back to on-demand assembly for cold users and super-followers.

### Detailed Description

This architecture deliberately blurs the push/pull boundary. It divides users into three buckets:

1. **Active users** (e.g., top 20% by read frequency): Their feeds are pre-materialized in regional caches (one per geographic region, e.g., AWS region or POP). A post is pushed only to the regional caches where the author's followers are concentrated. This dramatically reduces global write amplification while preserving O(1) reads for the most valuable users.

2. **Cold users** (long tail, infrequent readers): Their feeds are assembled on-demand using a pull-based query against central post indices, with a longer cache TTL (e.g., 5 minutes) since they read infrequently.

3. **Super-followers** (users following >1,000 accounts or authors with >100K followers): These are handled via a dedicated "hot index" — a heavily cached, time-windowed global post stream that is filtered at read time. This avoids both massive per-post fan-out and expensive multi-author merges.

Invalidation uses a **probabilistic approach**: instead of explicitly removing posts on unfollow, each cached feed entry carries a lightweight bloom filter of the user's current follow set. On read, the system checks the post's author against the bloom filter. If the bloom filter says "not followed," the entry is skipped and the cache entry is lazily removed. The bloom filter is refreshed periodically (e.g., every 60 seconds) from the strongly consistent follow graph. This trades a tiny false-positive rate (a followed author being incorrectly filtered) for massive savings in invalidation infrastructure.

### Key Design Decisions and Rationale

- **Regional fan-out**: Pushing to regional caches instead of per-user keys reduces keyspace explosion. A post by a US-based author is pushed to the US-East and US-West regional feed pools, not to 500,000 individual user keys.
- **Three-tier user segmentation**: Acknowledges that not all users are equal. Optimizing for active users maximizes cache hit ratio while minimizing write amplification.
- **Probabilistic invalidation via bloom filters**: Eliminates the need for a complex invalidation pipeline. Unfollows are reflected in the bloom filter within 60 seconds, meeting the consistency requirement with high probability. False positives are acceptable because they are rare and transient.
- **Hot index for super-followers**: A shared, time-sorted window of recent posts (e.g., last 24 hours) is cached globally. Users with massive follow lists filter this window rather than merging hundreds of author indices.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| Balanced read/write cost — no extreme amplification on either side | System has three distinct code paths (active, cold, super) |
| >95% cache hit ratio by targeting active users specifically | Bloom filter false positives may very rarely hide legitimate posts |
| Scales gracefully with follow-graph size and celebrity accounts | Regional cache coherence requires cross-region sync for travelers |
| Minimal explicit invalidation infrastructure | Cold-user read latency is higher than active users |
| Geographic latency reduction via regional caches | Most complex to implement and operate |

- **Probability of success**: 0.65 — This is the most theoretically optimal but least battle-tested of the three. It requires sophisticated traffic analysis to classify users and tune thresholds.
- **Complexity**: High — Three subsystems, regional replication, bloom filter management, and dynamic user classification all add surface area.
- **Potential risks and failure modes**:
  1. **User misclassification**: An active user temporarily classified as "cold" due to a modeling error will experience poor latency. Mitigation: conservative thresholds, real-time reclassification on read patterns.
  2. **Bloom filter saturation**: If a user follows too many accounts, the bloom filter false-positive rate rises. Mitigation: dynamically size bloom filters, or fall back to precise set membership for high-follow users.
  3. **Regional inconsistency for traveling users**: A user in Europe reading from EU regional cache may miss a post from a US author if cross-region propagation lags. Mitigation: user-affinity routing (pin users to a home region), or fallback to central index on cache miss.
  4. **Threshold tuning is fragile**: The boundaries between active/cold/super are heuristic. Shifts in user behavior can invalidate tuning. Mitigation: automated threshold adjustment based on hit-ratio and latency metrics.

---

## Comparison Summary

| Aspect | Approach 1: Pull + Multi-Tier | Approach 2: Push + Materialized | Approach 3: Hybrid + Regional + Probabilistic |
|--------|------------------------------|--------------------------------|-----------------------------------------------|
| **Read Latency** | Medium-High (merge cost) | Very Low (O(1) lookup) | Low for active, Medium for cold |
| **Write Cost** | Very Low (O(1) index) | Very High (O(F) fan-out) | Medium (regional push + index) |
| **Cache Hit Ratio** | ~90-95% (depends on re-reads) | >99% | >95% (by design) |
| **Unfollow Handling** | Implicit (next read) | Explicit invalidation job | Probabilistic bloom filter |
| **Super-User Handling** | Read hotspot risk | Write amplification cap | Dedicated hot index |
| **Storage Cost** | Low (indices only) | Very High (per-user feeds) | Medium (regional + hot index) |
| **Operational Complexity** | Medium | High | High |
| **Probability of Success** | 0.75 | 0.70 | 0.65 |

---

*End of Phase 1: Exploration*
