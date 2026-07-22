# Phase 1 (Exploration): Tree of Thoughts — Social Media Feed API Caching Strategy

## Problem Breakdown

### Read Patterns
- **Volume**: 100M users reading feeds, likely multiple times per day. Assuming each user checks their feed 10x/day, that's ~1B feed reads/day or ~11.5K reads/second on average, with peaks likely 5-10x higher.
- **Access Pattern**: Each read fetches a personalized, paginated view of posts from accounts the user follows, sorted by recency. Most reads hit the first page (most recent posts).
- **Latency Sensitivity**: Feed reads must be fast (<100ms). Any per-request computation across large datasets is dangerous at this scale.

### Write Patterns
- **Volume**: 10K posts/second globally.
- **Fanout Multiplier**: A post from a user with 1M followers creates 1M feed entries. A celebrity post can trigger 100M+ fanouts.
- **Burst Risk**: Viral events or celebrity posts create massive write spikes that can overwhelm the system if not handled carefully.

### Consistency Needs
- **New Post Visibility**: Posts must appear in followers' feeds within 5 minutes. This is bounded eventual consistency — not strict consistency, but with an SLA.
- **Unfollow Invalidation**: When a user unfollows someone, cached feed data must be invalidated. Stale data showing posts from an unfollowed account is a user-facing bug.

---

## Solution Space Mapping

The major dimensions where solutions differ:

| Dimension | Options |
|-----------|---------|
| **Fanout Strategy** | Push (precompute on write) / Pull (compute on read) / Hybrid (selective push-pull) |
| **Cache Topology** | Single-tier (one cache layer) / Multi-tier (edge → app → distributed → DB) |
| **Cached Data Granularity** | Full feed HTML / Feed list of post IDs / Post content separately / Inverted index |
| **Consistency Mechanism** | TTL-based expiration / Active invalidation / Eventual with background refresh |
| **Celebrity Handling** | Same as normal users / Special path (bypass, separate queue, rate limit) |
| **Invalidation Scope** | Per-user feed / Per-post global / Per-follower relationship |

The three approaches below explore distinctly different regions of this solution space.

---

## Approach A: Write-Time Fanout with Sharded Feed Cache (Push Model)

**Summary:** Precompute every user's feed at write time by fanning out post IDs to all followers' cached feed lists, making reads a simple cache lookup.

### Detailed Description

In this approach, every user's feed is materialized ahead of time in a distributed cache (e.g., Redis Cluster). When a user creates a post, an asynchronous fanout worker pushes the post ID into a sorted list (by timestamp) stored in the cache for each follower. The read path is trivial: fetch the top N post IDs from the user's feed cache entry, then hydrate post content from a separate post content cache. No database joins or aggregations happen at read time.

The cache entry for each user contains an ordered list of post IDs representing their feed. This list is capped at a reasonable size (e.g., last 1,000 posts) to bound memory. Post content is stored in a separate content-addressable cache keyed by post ID, enabling deduplication — if two followers see the same post, the content is cached once. TTLs are set on both feed lists and post content (e.g., 24-48 hours), with active invalidation on unfollow events.

Unfollow invalidation is handled by publishing an invalidation event to a message bus; workers consume these events and rebuild the affected user's feed list from the database (or remove posts from the unfollowed account within the cached list, if the system tracks provenance per entry). Given the 5-minute consistency window, fanout can be asynchronous and batched — posts are queued and processed by worker pools, with priority queues ensuring normal users are processed quickly while celebrity fanouts may be throttled or sharded across more workers.

### Key Design Decisions and Rationale

1. **Push fanout to cache on write**: Trading write latency/complexity for read simplicity. At 100M users, read volume dominates write volume by orders of magnitude. Optimizing reads is the right economic trade-off.
2. **Post IDs in feed cache, content separate**: Reduces duplication. Without this, a viral post cached inside 10M users' feeds wastes enormous memory. Separating content allows a single content cache entry to serve all viewers.
3. **Asynchronous fanout with message queues**: The 5-minute SLA permits asynchronicity. Batching and prioritizing fanout jobs smooths out write spikes.
4. **Capped feed list with TTL**: Prevents unbounded memory growth. Older posts fall off naturally; users rarely scroll deep into history.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| Sub-50ms read latency (cache hit) | Massive write amplification on celebrity posts |
| Extremely simple, predictable read path | High cache memory footprint (one list per user) |
| Easy pagination and sorting | Complex fanout infrastructure (queues, workers, retries) |
| Straightforward hit ratio optimization | Unfollow requires active invalidation or rebuild |

### Probability of Success: 0.75

### Complexity: High

### Potential Risks and Failure Modes
- **Celebrity Death Spiral**: A user with 50M followers posting could generate 50M cache writes. Without special handling, this overwhelms fanout workers and delays posts for normal users. *Mitigation*: celebrity throttling, separate high-volume queues, or a hybrid fallback (see Approach C).
- **Cache Stampede on Invalidation**: Mass unfollow events (e.g., a scandal) trigger millions of feed rebuilds simultaneously. *Mitigation*: staggered rebuilds, rate limiting, and background refresh rather than full invalidation.
- **Feed List Truncation**: If the cached list is too short, deep pagination requires DB fallback. *Mitigation*: track pagination depth metrics and tune list size.
- **Hot Key Contention**: If sharding is poor, certain cache nodes handling popular users' feeds can become bottlenecks. *Mitigation*: consistent hashing with virtual nodes, local cache replicas.

---

## Approach B: Read-Time Aggregation with Inverted Index Cache (Pull Model)

**Summary:** Do not precompute feeds; instead cache recent posts per author and merge them on read using an inverted index of follow relationships.

### Detailed Description

This approach inverts the traditional fanout model. Instead of writing post IDs into every follower's feed cache, posts are only written once — to the author's own "recent posts" cache entry. When a user requests their feed, the system fetches the list of accounts they follow (cached), then concurrently retrieves the most recent posts from each followed account's cached recent-posts list. These lists are merged, sorted by timestamp, and paginated in memory, with post content hydrated from a shared content cache.

The critical insight is that most users follow a relatively small number of accounts (e.g., median ~200), and they primarily care about the most recent few posts from each. Each author's "recent posts" cache stores only their last K posts (e.g., 50-100), which is sufficient to construct any follower's first few feed pages without touching the database. The follow-relationship list per user is also cached and versioned.

Unfollow invalidation is nearly free: the follow list cache is updated, and subsequent reads simply no longer query the unfollowed author's cache. There is no per-feed cache entry to invalidate because no feed was precomputed. The 5-minute consistency requirement is naturally satisfied because new posts appear in the author's cache immediately and are picked up by the next read.

To optimize, the system can pre-warm the recent-posts caches for highly followed accounts and use request coalescing when multiple users follow the same popular author (e.g., deduplicate concurrent fetches for @celebrity's recent posts).

### Key Design Decisions and Rationale

1. **No per-user feed cache**: Eliminates the write amplification problem entirely. The write path is O(1) regardless of follower count.
2. **Per-author recent-posts cache**: Assumes temporal locality — followers only need recent posts. Bounded cache entries per author (not per follower) dramatically reduce total cache size.
3. **Read-time merge and sort**: Modern CPUs can sort a few thousand items in microseconds. With median follow counts of ~200, merging is trivially fast. Even at 10,000 follows, it's manageable with efficient data structures.
4. **Lazy consistency**: No explicit invalidation for new posts or unfollows — state changes are reflected naturally on the next read. This eliminates an entire class of invalidation bugs.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| Zero write amplification (O(1) writes per post) | Read latency is higher and more variable (N cache lookups + merge + sort) |
| Dramatically lower cache memory usage | Cache hit ratio harder to achieve (>95% requires all N author caches to hit) |
| Trivial unfollow semantics (just update follow list) | Read performance degrades with high follow counts (power users suffer) |
| No fanout queues or workers needed | Pagination is stateless but computationally heavier; deep pages are expensive |
| Natural resilience to celebrity posts | Cannot easily precompute or push "breaking news" to all followers |

### Probability of Success: 0.60

### Complexity: Medium

### Potential Risks and Failure Modes
- **The Power-User Penalty**: A user following 10,000 accounts triggers 10,000 cache lookups per feed read. Even with concurrency, this increases tail latency significantly and risks missing the 95% hit ratio if any author's cache is cold. *Mitigation*: cap follow counts, use local caching for popular authors, or fall back to precomputed feeds for heavy users.
- **Read-Time Hot Spots**: Extremely popular authors (e.g., @elonmusk) have their recent-posts cache hit by millions of reads. *Mitigation*: replicate hot author caches across nodes, use local in-process caches, or CDN-edge caching for public content.
- **Feed Merge Consistency Edge Cases**: If an author's cache expires between fetching the follow list and fetching posts, the merged feed may appear inconsistent (gaps). *Mitigation*: use snapshot-style versioning or accept the 5-minute eventual consistency window.
- **Cache Hit Ratio Fragility**: A >95% hit ratio requires *every* author cache in a follow list to be warm. One cold author cache out of 200 means a DB lookup. *Mitigation*: proactive cache warming for all authors with recent activity, or tolerate a lower effective hit ratio for the full read path.

---

## Approach C: Hybrid Push-Pull with Tiered Cache and Celebrity Bypass

**Summary:** Use push fanout for normal users but dynamically switch to pull-based aggregation for celebrities, layered across a multi-tier cache topology.

### Detailed Description

This hybrid approach combines the best of both worlds by dynamically selecting the fanout strategy based on the author's follower count. A configurable threshold (e.g., 1M followers) separates "normal users" from "celebrities." For normal users, the system uses Approach A's push model: posts are fanned out to followers' feed caches asynchronously. For celebrities, the system uses Approach B's pull model: the celebrity's posts are not fanned out; instead, their recent posts are stored in a highly replicated, hot-tier cache, and followers' feeds merge in the celebrity's content at read time.

The cache topology is tiered to maximize hit ratios and minimize latency:
- **Tier 1 (Edge/CDN)**: Public post content and static assets. Anonymous or semi-public feeds may be cached at the edge.
- **Tier 2 (Application In-Process Cache)**: Hot follow lists, celebrity recent-posts caches, and popular feed fragments. This handles the bulk of requests without network hops.
- **Tier 3 (Distributed Cache Cluster)**: Full feed lists for normal users, post content for less popular posts, and follow relationship graphs.
- **Tier 4 (Database)**: Source of truth for all data; used only on cache misses and rebuilds.

The system maintains a real-time "social graph metadata" service that tracks follower counts and fanout costs. When a user crosses the celebrity threshold, their posting path automatically switches to pull mode, and their recent posts are promoted to Tier 2 (in-process) caches across application servers. Feed reads for users who follow celebrities perform a hybrid merge: fetch the precomputed feed cache (which excludes celebrity posts) and concurrently fetch celebrity recent posts from Tier 2, then merge.

Unfollow invalidation is handled per strategy: for normal unfollows, the precomputed feed cache is actively invalidated or rebuilt. For celebrity unfollows, only the follow list cache is updated, and the celebrity's posts disappear naturally on the next read (no feed cache rebuild needed).

### Key Design Decisions and Rationale

1. **Dynamic strategy selection based on follower count**: The push model works beautifully for low-to-moderate fanout but collapses at celebrity scale. The pull model works beautifully for high-read, low-write scenarios but struggles with high follow counts. Selecting based on the author's properties places each post on the optimal path.
2. **Tiered cache with hot celebrity promotion**: Celebrity content is read by millions but written once. Promoting it to in-process caches (Tier 2) turns what would be 1M distributed cache lookups into local memory accesses on each app server.
3. **Feed fragments rather than full feeds in Tier 2**: Instead of caching full feeds at the edge (which are infinitely variable due to personalization), cache the "components" (post content, author recent lists) and assemble them at the application layer. This maximizes cache reusability.
4. **Unified merge layer**: Whether a feed contains 0 or 10 celebrity accounts, the read path is the same: fetch base feed + fetch celebrity posts + merge. This keeps the API layer simple despite the backend complexity.

### Trade-offs

| What You Gain | What You Sacrifice |
|---------------|-------------------|
| Optimal read latency for both normal and celebrity cases | Highest implementation complexity — two complete systems to build and operate |
| Excellent resource efficiency (no wasted celebrity fanout writes) | Operational complexity: monitoring two paths, debugging strategy routing |
| Can exceed 95% hit ratio by leveraging multiple cache tiers | Risk of consistency anomalies at the push/pull boundary |
| Elastic handling of viral events (auto-switch to pull on follower spikes) | More moving parts = more failure modes |
| Graceful degradation if one tier fails | Feed merge logic must handle partial data (e.g., celebrity cache miss while base feed cache hits) |

### Probability of Success: 0.85

### Complexity: High

### Potential Risks and Failure Modes
- **Threshold Oscillation**: A user hovering near the 1M follower threshold could flip between push and pull repeatedly, causing inconsistent behavior. *Mitigation*: use hysteresis (e.g., switch to pull at 1M, back to push only if dropping below 900K) and async transitions.
- **Merge Logic Bugs**: The read-time merge of base feed + celebrity posts is subtle. Duplicate posts (if a celebrity post was also fanned out during a transition period), ordering edge cases, and missing posts are all possible. *Mitigation*: idempotent post IDs in merge, deduplication step, and comprehensive integration testing.
- **Tier 2 Cache Coherence**: In-process caches on app servers can drift. If a celebrity deletes a post, not all Tier 2 caches may reflect it immediately. *Mitigation*: short TTLs on Tier 2 (e.g., 30-60s) with invalidation broadcast, or accept the 5-minute window.
- **Operational Complexity**: Debugging why a specific user sees a specific post requires tracing which strategy was used for which author, which cache tier served which component, and how the merge behaved. *Mitigation*: rich distributed tracing and structured logging throughout the pipeline.
- **Cold Start for New Celebrities**: When a normal user suddenly goes viral and crosses the threshold, their posts may be mid-fanout while the system switches to pull. *Mitigation*: gradual transition, drain in-flight fanouts, and temporary dual-writing during the switch.

---

## Comparison Summary

| Attribute | Approach A: Push Fanout | Approach B: Pull Aggregation | Approach C: Hybrid Tiered |
|-----------|------------------------|------------------------------|---------------------------|
| **Fanout Strategy** | Push | Pull | Hybrid (dynamic) |
| **Read Latency** | Very Low (~10-30ms) | Moderate (~50-150ms) | Very Low (~15-40ms) |
| **Write Cost** | High (O(followers)) | Low (O(1)) | Medium (O(followers) for normals, O(1) for celebs) |
| **Cache Memory** | Very High | Low | Medium |
| **Hit Ratio Achievability** | Easy >95% | Harder >95% | Easiest >95% (multi-tier) |
| **Unfollow Handling** | Active invalidation/rebuild | Lazy (update follow list) | Strategy-dependent |
| **Celebrity Resilience** | Poor | Good | Excellent |
| **Implementation Complexity** | High | Medium | High |
| **Operational Complexity** | Medium | Low | High |
| **Probability of Success** | 0.75 | 0.60 | 0.85 |
