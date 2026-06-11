/**
 * Instagram API — barrel re-export of all sub-modules.
 *
 * This index file re-exports every public function, class, type, and interface
 * from the sub-modules so that existing imports from `instagramApi.js` continue
 * to work unchanged via the thin re-export in the parent file.
 */

// Batch requests
export { batchRequest } from "./batch.js";
// Audio — search/retrieve Meta-native audio and media audio metadata
export {
	discoverInstagramAudioReplacements,
	getInstagramAudioMetadata,
	getInstagramMediaAudioType,
	normalizeInstagramAudioAsset,
	searchInstagramAudio,
	type IGAudioAsset,
	type IGAudioReplacementMode,
	type IGAudioReplacementParams,
	type IGAudioSearchParams,
	type IGAudioType,
	type IGMediaAudioType,
} from "./audio.js";
// Collaboration invites
export {
	acceptCollaboration,
	declineCollaboration,
	getCollaborationInvites,
} from "./collaboration.js";
// Comments — CRUD + private reply
export {
	deleteComment,
	getMediaComments,
	hideComment,
	replyToComment,
	sendPrivateReply,
} from "./comments.js";
// Discovery — business discovery, hashtag search
export {
	getBusinessDiscovery,
	getHashtagRecentMedia,
	getHashtagTopMedia,
	searchHashtag,
} from "./discovery.js";
// Insights — post/story/account metrics, demographics, online followers
export {
	getCarouselChildInsights,
	getIgFollowerCount,
	getInstagramAccountInsights,
	getInstagramDemographics,
	getInstagramPostMetrics,
	getInstagramStoryMetrics,
	getOnlineFollowers,
} from "./insights.js";
// Media — user media, stories, saved/tagged/mentioned media, mentions reply
export {
	getCollaborativeMedia,
	getInstagramStories,
	getMentionedMedia,
	getSavedMedia,
	getTaggedMedia,
	getUserMedia,
	replyToMention,
	searchCollaborativeMedia,
	setInstagramLike,
} from "./media.js";
// Messaging — conversations, DMs, templates, reactions
export {
	getConversationMessages,
	getConversations,
	getUserProfile,
	sendButtonTemplate,
	sendGenericTemplate,
	sendHeartSticker,
	sendMediaMessage,
	sendMessage,
	sendMessageReaction,
	sendMultiImageMessage,
	sendPostShare,
	sendQuickReplies,
	sendSenderAction,
} from "./messaging.js";
// Messenger profile — persistent menus, ice breakers, welcome flows
export {
	createWelcomeMessageFlow,
	deleteIceBreakers,
	deletePersistentMenu,
	deleteWelcomeMessageFlow,
	getIceBreakers,
	getPersistentMenu,
	getWelcomeMessageFlows,
	setIceBreakers,
	setPersistentMenu,
} from "./messenger-profile.js";
// Orchestrator — shared pre/post-publish pipeline (transform, media check, sync)
export { type IGPublishOptions, orchestrateIGPublish } from "./orchestrate.js";
// Publishing — container management, posting, publishing limits, media deletion
export {
	checkContainerReady,
	checkContainerStatus,
	checkPublishingLimit,
	deleteFromInstagram,
	deleteInstagramMedia,
	postToInstagram,
	publishContainer,
	toggleCommentEnabled,
} from "./publishing.js";
// Shared types, error handling, and utilities
export {
	type ButtonTemplateButton,
	type ContainerStatus,
	type IceBreaker,
	type IceBreakerLocale,
	type IGAccountInsights,
	// Error class
	IGApiError,
	// Types
	type IGCarouselChild,
	type IGCarouselChildRaw,
	type IGCollaborationInvite,
	type IGComment,
	type IGConversation,
	type IGDemographicsBreakdown,
	type IGMediaItem,
	type IGMediaType,
	type IGMessage,
	type IGPaging,
	type IGPostData,
	type IGPostingResult,
	type IGPostMetrics,
	type IGStory,
	type IGStoryMetrics,
	type IGUserProfile,
	type IGWelcomeFlow,
	type PersistentMenuItem,
	type PersistentMenuLocale,
	type QuickReply,
	type TemplateButton,
	type TemplateElement,
	type WelcomeFlowQuickReply,
} from "./shared.js";
