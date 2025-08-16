'use client';

import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  type AgentState,
  type ReceivedChatMessage,
  useRoomContext,
  useVoiceAssistant,
} from '@livekit/components-react';
import { toastAlert } from '@/components/alert-toast';
import { AgentControlBar } from '@/components/livekit/agent-control-bar/agent-control-bar';
import { ChatEntry } from '@/components/livekit/chat/chat-entry';
import { ChatMessageView } from '@/components/livekit/chat/chat-message-view';
import { MediaTiles } from '@/components/livekit/media-tiles';
import useChatAndTranscription from '@/hooks/useChatAndTranscription';
import { useDebugMode } from '@/hooks/useDebug';
import type { AppConfig } from '@/lib/types';
import { cn } from '@/lib/utils';
import { ConversationStatus, type ConversationSection } from '@/components/conversation-status';
import { RoomEvent } from 'livekit-client';
import { CopyIcon } from '@phosphor-icons/react/dist/ssr';

function isAgentAvailable(agentState: AgentState) {
  return agentState == 'listening' || agentState == 'thinking' || agentState == 'speaking';
}

interface SessionViewProps {
  appConfig: AppConfig;
  disabled: boolean;
  sessionStarted: boolean;
  mode: 'lesson' | 'copilot';
  onEndSession?: () => void;
}

export const SessionView = React.forwardRef<
  HTMLElement,
  React.ComponentProps<'main'> & SessionViewProps
>(function SessionView(
  { appConfig, disabled, sessionStarted, mode, onEndSession, className, ...rest },
  ref
) {
  const { state: agentState } = useVoiceAssistant();
  const [chatOpen, setChatOpen] = useState(false);
  const { messages, send } = useChatAndTranscription();
  const room = useRoomContext();

  const createInitialSections = (): ConversationSection[] => ([
    { id: '0', title: 'Introduction', status: 'active' },
    { id: '1', title: 'Lesson 1: AI Alignment', status: 'pending' },
    { id: '2', title: 'Lesson 2: Critical Thinking', status: 'pending' },
    { id: '3', title: 'Wrap-up', status: 'pending' },
  ]);

  const [sections, setSections] = useState<ConversationSection[]>(createInitialSections());
  const [promptText, setPromptText] = useState<string>('');
  const [copiedAt, setCopiedAt] = useState<number>(0);

  // Reset to a fresh state for each session start
  useEffect(() => {
    if (sessionStarted) {
      setSections(createInitialSections());
      setPromptText('');
    }
  }, [sessionStarted]);

  // Listen for backend updates via LiveKit data messages
  useEffect(() => {
    function onData(payload: Uint8Array) {
      try {
        const text = new TextDecoder().decode(payload);
        const msg = JSON.parse(text);
        if (msg?.type === 'lesson_status' && typeof msg.id === 'string' && typeof msg.status === 'string') {
          setSections((prev) => {
            const next = prev.map((s) => (s.id === msg.id ? { ...s, status: msg.status } : s));
            // Auto-advance: when a section becomes complete, mark the next pending as active
            if (msg.status === 'completed') {
              const idx = next.findIndex((s) => s.id === msg.id);
              const nextIdx = idx >= 0 ? idx + 1 : -1;
              if (nextIdx >= 0 && nextIdx < next.length && next[nextIdx].status === 'pending') {
                next[nextIdx] = { ...next[nextIdx], status: 'active' };
              }
            }
            return next;
          });
        } else if (msg?.type === 'prompt_update' && typeof msg.text === 'string') {
          setPromptText(msg.text);
        }
      } catch {
        // ignore malformed payloads
      }
    }

    room.on(RoomEvent.DataReceived, onData as any);
    return () => {
      room.off(RoomEvent.DataReceived, onData as any);
    };
  }, [room]);

  useDebugMode();

  async function handleSendMessage(message: string) {
    await send(message);
  }

  useEffect(() => {
    if (sessionStarted) {
      const timeout = setTimeout(() => {
        if (!isAgentAvailable(agentState)) {
          const reason =
            agentState === 'connecting'
              ? 'Agent did not join the room. '
              : 'Agent connected but did not complete initializing. ';

          toastAlert({
            title: 'Session ended',
            description: (
              <p className="w-full">
                {reason}
                <a
                  target="_blank"
                  rel="noopener noreferrer"
                  href="https://docs.livekit.io/agents/start/voice-ai/"
                  className="whitespace-nowrap underline"
                >
                  See quickstart guide
                </a>
                .
              </p>
            ),
          });
          room.disconnect();
          onEndSession?.();
        }
      }, 10_000);

      return () => clearTimeout(timeout);
    }
  }, [agentState, sessionStarted, room, onEndSession]);

  const { supportsChatInput, supportsVideoInput, supportsScreenShare } = appConfig;
  const capabilities = {
    supportsChatInput,
    supportsVideoInput,
    supportsScreenShare,
  };

  return (
    <main
      ref={ref}
      {...({ inert: disabled } as any)}
      className={cn(
        // prevent page scrollbar
        // when !chatOpen due to 'translate-y-20'
        !chatOpen && 'max-h-svh overflow-hidden',
        className
      )}
      {...rest}
    >
      <div className="mx-auto grid min-h-svh w-full max-w-5xl grid-cols-1 gap-6 px-3 pt-32 pb-40 md:grid-cols-[300px_1fr] md:px-0 md:pt-36 md:pb-48">
        <div className="md:sticky md:top-36 md:z-10 hidden md:block">
          {mode === 'lesson' && <ConversationStatus sections={sections} />}
          {promptText !== '' && (
            <div className="mt-8">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold tracking-wide text-fg1 uppercase">Prompt</h2>
                <button
                  type="button"
                  className="group inline-flex items-center gap-1 rounded-md border border-fg2/40 px-2 py-1 text-xs font-medium text-fg1 hover:bg-fg2/10"
                  title={copiedAt ? 'Copied!' : 'Copy prompt'}
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(promptText);
                      setCopiedAt(Date.now());
                      setTimeout(() => setCopiedAt(0), 1500);
                    } catch {}
                  }}
                  aria-label="Copy prompt"
                >
                  {copiedAt ? (
                    <span className="inline-flex h-4 w-4 items-center justify-center text-green-600">✓</span>
                  ) : (
                    <CopyIcon className="h-4 w-4" />
                  )}
                  <span className="hidden md:inline">{copiedAt ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
              <div className="mt-3 max-h-64 overflow-auto rounded-lg border border-fg2/30 bg-background p-3 text-sm leading-6 whitespace-pre-wrap break-words">
                {promptText}
              </div>
            </div>
          )}
        </div>
        <ChatMessageView
          className={cn(
            'min-h-svh w-full transition-[opacity,translate] duration-300 ease-out',
            chatOpen ? 'translate-y-0 opacity-100 delay-200' : 'translate-y-20 opacity-0'
          )}
        >
          <div className="space-y-3 whitespace-pre-wrap">
            <AnimatePresence>
              {messages.map((message: ReceivedChatMessage) => (
                <motion.div
                  key={message.id}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 1, height: 'auto', translateY: 0.001 }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                >
                  <ChatEntry hideName key={message.id} entry={message} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </ChatMessageView>
      </div>

      <div className="bg-background mp-12 fixed top-0 right-0 left-0 h-32 md:h-36">
        {/* skrim */}
        <div className="from-background absolute bottom-0 left-0 h-12 w-full translate-y-full bg-gradient-to-b to-transparent" />
      </div>

      <MediaTiles chatOpen={chatOpen} />

      <div className="bg-background fixed right-0 bottom-0 left-0 z-50 px-3 pt-2 pb-3 md:px-12 md:pb-12">
        <motion.div
          key="control-bar"
          initial={{ opacity: 0, translateY: '100%' }}
          animate={{
            opacity: sessionStarted ? 1 : 0,
            translateY: sessionStarted ? '0%' : '100%',
          }}
          transition={{ duration: 0.3, delay: sessionStarted ? 0.5 : 0, ease: 'easeOut' }}
        >
          <div className="relative z-10 mx-auto w-full max-w-2xl">
            {appConfig.isPreConnectBufferEnabled && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{
                  opacity: sessionStarted && messages.length === 0 ? 1 : 0,
                  transition: {
                    ease: 'easeIn',
                    delay: messages.length > 0 ? 0 : 0.8,
                    duration: messages.length > 0 ? 0.2 : 0.5,
                  },
                }}
                aria-hidden={messages.length > 0}
                className={cn(
                  'absolute inset-x-0 -top-12 text-center',
                  sessionStarted && messages.length === 0 && 'pointer-events-none'
                )}
              >
                <p className="animate-text-shimmer inline-block !bg-clip-text text-sm font-semibold text-transparent">
                  Agent is listening
                </p>
              </motion.div>
            )}

            <AgentControlBar
              capabilities={capabilities}
              onChatOpenChange={setChatOpen}
              onSendMessage={handleSendMessage}
              onDisconnect={onEndSession}
            />
          </div>
          {/* skrim */}
          <div className="from-background border-background absolute top-0 left-0 h-12 w-full -translate-y-full bg-gradient-to-t to-transparent" />
        </motion.div>
      </div>
    </main>
  );
});
