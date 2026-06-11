/**
 * Thread Grouping Utilities
 * Groups flat reply list into threaded conversations by parent post
 */

import {
  ThreadReply,
  ThreadPost,
  ThreadedConversation,
  ThreadSortOption,
  toDate,
} from "../types.js";

/**
 * Groups replies by their parent post ID and enriches with post data
 * @param replies - Flat array of ThreadReply objects
 * @param posts - Array of ThreadPost objects for enrichment
 * @returns Array of ThreadedConversation sorted by latest reply
 */
export function groupRepliesByThread(
  replies: ThreadReply[],
  posts: ThreadPost[],
): ThreadedConversation[] {
  // Create a map for quick post lookup
  const postMap = new Map(posts.map((p) => [p.id, p]));

  // Group replies by postId
  const grouped = new Map<string, ThreadReply[]>();
  replies.forEach((reply) => {
    const existing = grouped.get(reply.postId) || [];
    grouped.set(reply.postId, [...existing, reply]);
  });

  // Convert to ThreadedConversation array
  const conversations: ThreadedConversation[] = Array.from(
    grouped.entries(),
  ).map(([postId, threadReplies]) => {
    const post = postMap.get(postId);

    // Sort replies chronologically (oldest first) within thread
    const sortedReplies = [...threadReplies].sort((a, b) => {
      const timeA = toDate(a.timestamp).getTime();
      const timeB = toDate(b.timestamp).getTime();
      return timeA - timeB;
    });

    // Get the latest reply timestamp for sorting threads
    const latestReply = sortedReplies[sortedReplies.length - 1];
    const latestReplyAt = latestReply
      ? toDate(latestReply.timestamp)
      : new Date();

    // Build parent post info - use post data if available, fallback to reply's originalPostContent
    const parentPost = post
      ? {
          id: post.id,
          content: post.content,
          mediaUrls: post.mediaUrls || [],
          publishedAt: post.scheduledDate
            ? new Date(post.scheduledDate)
            : new Date(),
          metrics: {
            likes: post.likes || 0,
            replies: post.replies || 0,
          },
        }
      : {
          // Fallback when post is not found (deleted or not cached)
          id: postId,
          content:
            sortedReplies[0]?.originalPostContent || "[Post unavailable]",
          mediaUrls: [],
          publishedAt: new Date(),
          metrics: {
            likes: 0,
            replies: sortedReplies.length,
          },
        };

    return {
      postId,
      accountId: sortedReplies[0]?.accountId || "",
      accountHandle: sortedReplies[0]?.accountHandle || "",
      parentPost,
      replies: sortedReplies,
      unreadCount: sortedReplies.filter((r) => !r.isRead).length,
      latestReplyAt,
    };
  });

  // Sort threads by latest reply (most recent first)
  return conversations.sort(
    (a, b) => b.latestReplyAt.getTime() - a.latestReplyAt.getTime(),
  );
}

/**
 * Sorts threads by the specified criteria
 * @param threads - Array of ThreadedConversation
 * @param sortBy - Sort option: 'latest', 'unread', or 'engagement'
 * @returns Sorted copy of threads array
 */
export function sortThreads(
  threads: ThreadedConversation[],
  sortBy: ThreadSortOption,
): ThreadedConversation[] {
  return [...threads].sort((a, b) => {
    switch (sortBy) {
      case "unread":
        // Sort by unread count DESC, then by latest reply
        if (b.unreadCount !== a.unreadCount) {
          return b.unreadCount - a.unreadCount;
        }
        return b.latestReplyAt.getTime() - a.latestReplyAt.getTime();

      case "engagement":
        // Sort by total reply count DESC
        if (b.replies.length !== a.replies.length) {
          return b.replies.length - a.replies.length;
        }
        return b.latestReplyAt.getTime() - a.latestReplyAt.getTime();

      case "oldest":
        // Sort by latest reply timestamp ASC
        return a.latestReplyAt.getTime() - b.latestReplyAt.getTime();

      case "latest":
      default:
        // Sort by latest reply timestamp DESC
        return b.latestReplyAt.getTime() - a.latestReplyAt.getTime();
    }
  });
}

/**
 * Filters threads based on search query
 * @param threads - Array of ThreadedConversation
 * @param query - Search string (matches username or reply text)
 * @returns Filtered threads
 */
export function filterThreadsBySearch(
  threads: ThreadedConversation[],
  query: string,
): ThreadedConversation[] {
  if (!query.trim()) return threads;

  const searchLower = query.toLowerCase().trim();

  return threads.filter((thread) => {
    // Check parent post content
    if (thread.parentPost.content.toLowerCase().includes(searchLower)) {
      return true;
    }

    // Check if any reply matches
    return thread.replies.some(
      (reply) =>
        reply.text.toLowerCase().includes(searchLower) ||
        reply.username.toLowerCase().includes(searchLower),
    );
  });
}

/**
 * Filters out hidden replies from threads
 * @param threads - Array of ThreadedConversation
 * @param showHidden - Whether to include hidden replies
 * @returns Threads with hidden replies filtered out (or included)
 */
export function filterHiddenReplies(
  threads: ThreadedConversation[],
  showHidden: boolean,
): ThreadedConversation[] {
  if (showHidden) return threads;

  return threads
    .map((thread) => ({
      ...thread,
      replies: thread.replies.filter((reply) => !reply.isHidden),
      // Recalculate unread count for visible replies only
      unreadCount: thread.replies.filter((r) => !r.isRead && !r.isHidden)
        .length,
    }))
    .filter((thread) => thread.replies.length > 0); // Remove threads with no visible replies
}

/**
 * Gets count statistics for display
 */
export function getThreadStats(threads: ThreadedConversation[]) {
  const totalReplies = threads.reduce((sum, t) => sum + t.replies.length, 0);
  const totalUnread = threads.reduce((sum, t) => sum + t.unreadCount, 0);
  const hiddenReplies = threads.reduce(
    (sum, t) => sum + t.replies.filter((r) => r.isHidden).length,
    0,
  );

  return {
    threadCount: threads.length,
    totalReplies,
    totalUnread,
    hiddenReplies,
  };
}
