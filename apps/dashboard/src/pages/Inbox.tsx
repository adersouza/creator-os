import { useEffect } from "react";
import { usePhoneChrome } from "@/hooks/usePhoneChrome";
import { NovaScreen } from "@/components/layout/NovaScreen";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { NovaDataPanel, NovaSection } from "@/components/ui/NovaPrimitives";
import { CommandPalette } from "@/components/inbox/CommandPalette";
import {
	ConversationListPane,
	MobileInbox,
} from "@/components/inbox/ConversationListPane";
import {
	EmptyDetail,
	ThreadDetailPane,
} from "@/components/inbox/ThreadDetailPane";
import {
	EmptyShell,
	InboxFilterBar,
	InboxHeader,
	InboxLoadingPane,
} from "@/components/inbox/InboxChrome";
import { Kbd } from "@/components/inbox/helpers";
import { useInboxController } from "@/components/inbox/useInboxController";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";

export function Inbox() {
	const inbox = useInboxController();
	const phoneChrome = usePhoneChrome();
	const { setCommandOpen, setSearch } = inbox;

	useEffect(() => {
		const openInboxCommand = () => setCommandOpen(true);
		const focusInboxSearch = () => {
			setSearch("");
			window.requestAnimationFrame(() => {
				document
					.querySelector<HTMLInputElement>("[data-inbox-search]")
					?.focus();
			});
		};

		window.addEventListener("juno33:inbox-command", openInboxCommand);
		window.addEventListener("juno33:inbox-search", focusInboxSearch);
		return () => {
			window.removeEventListener("juno33:inbox-command", openInboxCommand);
			window.removeEventListener("juno33:inbox-search", focusInboxSearch);
		};
	}, [setCommandOpen, setSearch]);

	return (
		<>
			{phoneChrome && inbox.mobileActive ? (
				<div className="min-h-[100dvh] flex flex-col pb-24">
					<ThreadDetailPane
						conversation={inbox.mobileActive}
						suggestion={inbox.suggestionsByKey.get(
							inbox.keyForConversation(inbox.mobileActive),
						)}
						identityAdvisory={inbox.identityAdvisories.get(
							inbox.mobileActive.id,
						)}
						replyText={inbox.replyText}
						onReplyChange={inbox.setReplyText}
						onSend={inbox.send}
						isSending={inbox.isSending}
						onBack={() => inbox.setMobileActiveId(null)}
						onRegenerateSuggestion={inbox.regenerateSuggestion}
						presenceLabel={inbox.draftingLabel}
						onComposerFocus={inbox.startDrafting}
						onComposerBlur={inbox.stopDrafting}
						replyRef={inbox.replyRef}
						liked={inbox.likedCommentIds.has(inbox.mobileActive.reply.replyToId)}
						likeBusy={inbox.likeBusyIds.has(inbox.mobileActive.reply.replyToId)}
						onToggleLike={inbox.toggleInstagramCommentLike}
						isDone={inbox.activeDone}
						needsAttention={inbox.activeNeedsAttention}
						onToggleDone={inbox.toggleActiveDone}
						onConvertToIdea={inbox.convertActiveToIdea}
						mobileChrome
					/>
				</div>
			) : phoneChrome ? (
				<div>
					<MobileInbox
						conversations={inbox.filtered}
						totalCount={inbox.filtered.length}
						scopedAccount={inbox.scopedAccount}
						activeId={inbox.mobileActiveId}
						tab={inbox.tab}
						platform={inbox.platform}
						onTabChange={inbox.setTab}
						tabCounts={inbox.counts}
						search={inbox.search}
						workflowFilter={inbox.workflowFilter}
						workflowCounts={inbox.workflowCounts}
						doneKeys={inbox.doneKeys}
						suggestionsByKey={inbox.suggestionsByKey}
						keyForConversation={inbox.keyForConversation}
						onSearchChange={inbox.setSearch}
						onWorkflowFilterChange={inbox.setWorkflowFilter}
						onOpen={(id) => {
							inbox.setActiveId(id);
							inbox.setMobileActiveId(id);
						}}
					/>
				</div>
			) : null}

			<NovaScreen
				width="full"
				density="compact"
				className={phoneChrome ? "hidden" : "flex h-[calc(100dvh-64px)] flex-col"}
			>
				<style>{`
          @keyframes inbox-msg-pulse {
            0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-oxblood) 35%, transparent); }
            70% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--color-oxblood) 0%, transparent); }
          }
          .inbox-live-dot { animation: inbox-msg-pulse 2s ease-out infinite; }
          @media (prefers-reduced-motion: reduce) { .inbox-live-dot { animation: none; } }
        `}</style>
				<InboxHeader
					total={inbox.filtered.length}
					platform={inbox.platform}
					scopedAccount={inbox.scopedAccount}
					accountCount={inbox.connectedAccounts.length}
					onClearScope={() => useAccountScopeStore.getState().clearScope()}
					onPlatformChange={inbox.setPlatform}
				/>
				<InboxFilterBar
					platform={inbox.platform}
					tab={inbox.tab}
					counts={inbox.counts}
					lockedToAccount={!!inbox.scopedAccount}
					onTabChange={inbox.setTab}
					onTablistKey={inbox.onTablistKey}
				/>

				{inbox.inboxLoading && !inbox.conversations.length ? (
					<InboxLoadingPane />
				) : inbox.showNoAccountsEmpty ? (
					<EmptyShell
						eyebrow="Inbox · no conversations yet"
						title="Nothing in the inbox"
						description="Instagram DMs and Threads replies or mentions from your connected accounts appear here. Connect an account to start receiving them."
						primaryLabel="Connect your first account"
						onPrimary={() => inbox.navigate("/accounts")}
						secondaryLabel="Back to overview"
						onSecondary={() => inbox.navigate("/dashboard")}
					/>
				) : inbox.showSyncPendingEmpty ? (
					<EmptyShell
						eyebrow="Inbox · sync in progress"
						title="Inbox syncs conversations as they arrive"
						description="We're pulling Instagram DMs and Threads replies or mentions into dedicated platform views. The first sync lands within an hour of account connection - new messages flow in live after that."
						secondaryLabel="Back to overview"
						onSecondary={() => inbox.navigate("/dashboard")}
					/>
				) : (
					<>
						<NovaDataPanel
							className="flex min-h-0 flex-1 flex-col"
							contentClassName="flex min-h-0 flex-1 p-0"
						>
							<ConversationListPane
								conversations={inbox.filtered}
								activeConversation={inbox.active}
								tab={inbox.tab}
								platform={inbox.platform}
								search={inbox.search}
								viewingThread={inbox.viewingThread}
								identityAdvisories={inbox.identityAdvisories}
								suggestionsByKey={inbox.suggestionsByKey}
								keyForConversation={inbox.keyForConversation}
								onSearchChange={inbox.setSearch}
								workflowFilter={inbox.workflowFilter}
								workflowCounts={inbox.workflowCounts}
								doneKeys={inbox.doneKeys}
								onWorkflowFilterChange={inbox.setWorkflowFilter}
								onOpen={(id) => {
									inbox.setActiveId(id);
									inbox.setViewingThread(true);
								}}
								onAcceptSuggestion={inbox.acceptSuggestion}
								onRejectSuggestion={inbox.rejectSuggestion}
							/>
							<section className="flex-1 flex flex-col min-w-0 transition-transform duration-300 md:translate-x-0 relative">
								{inbox.active ? (
									<ThreadDetailPane
										conversation={inbox.active}
										suggestion={inbox.activeSuggestion}
										identityAdvisory={inbox.identityAdvisories.get(
											inbox.active.id,
										)}
										replyText={inbox.replyText}
										onReplyChange={inbox.setReplyText}
										onSend={inbox.send}
										isSending={inbox.isSending}
										onBack={() => inbox.setViewingThread(false)}
										onRegenerateSuggestion={inbox.regenerateSuggestion}
										presenceLabel={inbox.draftingLabel}
										onComposerFocus={inbox.startDrafting}
										onComposerBlur={inbox.stopDrafting}
										replyRef={inbox.replyRef}
										liked={inbox.likedCommentIds.has(inbox.active.reply.replyToId)}
										likeBusy={inbox.likeBusyIds.has(inbox.active.reply.replyToId)}
										onToggleLike={inbox.toggleInstagramCommentLike}
										isDone={inbox.activeDone}
										needsAttention={inbox.activeNeedsAttention}
										onToggleDone={inbox.toggleActiveDone}
										onConvertToIdea={inbox.convertActiveToIdea}
									/>
								) : (
									<EmptyDetail />
								)}
							</section>
						</NovaDataPanel>
						<NovaSection className="mt-3 hidden shrink-0 flex-row items-center gap-4 text-[0.65625rem] text-muted-foreground md:flex">
							<span className="inline-flex items-center gap-1.5">
								<Kbd>J</Kbd>
								<Kbd>K</Kbd> navigate
							</span>
							<span className="inline-flex items-center gap-1.5">
								<Kbd>R</Kbd> reply
							</span>
							<span className="inline-flex items-center gap-1.5">
								<Kbd>D</Kbd> done
							</span>
							<span className="inline-flex items-center gap-1.5">
								<Kbd>I</Kbd> idea
							</span>
							<span className="inline-flex items-center gap-1.5">
								<Kbd>⌘</Kbd>
								<Kbd>↵</Kbd> send
							</span>
						</NovaSection>
					</>
				)}
			</NovaScreen>

			<ConfirmDialog
				open={!!inbox.safetyWarning}
				onClose={() => inbox.setSafetyWarning(null)}
				onConfirm={async () => {
					const action = inbox.safetyWarning?.action;
					inbox.setSafetyWarning(null);
					await action?.();
				}}
				title="This contradicts your last reply"
				description={inbox.safetyWarning?.description ?? ""}
				confirmLabel="Send anyway"
				cancelLabel="Keep editing"
			/>
			<CommandPalette
				open={inbox.commandOpen}
				conversations={inbox.filtered}
				commands={inbox.commandActions}
				onClose={() => inbox.setCommandOpen(false)}
				onJump={(id) => {
					inbox.setActiveId(id);
					inbox.setViewingThread(true);
				}}
			/>
		</>
	);
}
