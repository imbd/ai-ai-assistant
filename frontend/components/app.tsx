'use client';

import { useEffect, useMemo, useState } from 'react';
import { Room, RoomEvent } from 'livekit-client';
import { motion } from 'motion/react';
import { RoomAudioRenderer, RoomContext, StartAudio } from '@livekit/components-react';
import { toastAlert } from '@/components/alert-toast';
import { SessionView } from '@/components/session-view';
import { Toaster } from '@/components/ui/sonner';
import { Welcome } from '@/components/welcome';
import useConnectionDetails from '@/hooks/useConnectionDetails';
import type { AppConfig } from '@/lib/types';

const MotionWelcome = motion.create(Welcome);
const MotionSessionView = motion.create(SessionView);

interface AppProps {
  appConfig: AppConfig;
}

type Mode = 'lesson' | 'copilot';

export function App({ appConfig }: AppProps) {
  const room = useMemo(() => new Room(), []);
  const [sessionStarted, setSessionStarted] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);
  const { connectionDetails } = useConnectionDetails(mode ?? undefined);
  const [isHydrated, setIsHydrated] = useState(false);

  useEffect(() => {
    setIsHydrated(true);
  }, []);

  useEffect(() => {
    const onDisconnected = () => {
      setSessionStarted(false);
      setMode(null);
    };
    const onMediaDevicesError = (error: Error) => {
      toastAlert({
        title: 'Encountered an error with your media devices',
        description: `${error.name}: ${error.message}`,
      });
    };
    room.on(RoomEvent.MediaDevicesError, onMediaDevicesError);
    room.on(RoomEvent.Disconnected, onDisconnected);
    return () => {
      room.off(RoomEvent.Disconnected, onDisconnected);
      room.off(RoomEvent.MediaDevicesError, onMediaDevicesError);
    };
  }, [room]);

  // Begin the session only once we have connection details for the chosen mode
  useEffect(() => {
    if (mode && connectionDetails && !sessionStarted) {
      setSessionStarted(true);
    }
  }, [mode, connectionDetails, sessionStarted]);

  useEffect(() => {
    let aborted = false;
    if (sessionStarted && room.state === 'disconnected' && connectionDetails) {
      Promise.all([
        room.localParticipant.setMicrophoneEnabled(true, undefined, {
          preConnectBuffer: appConfig.isPreConnectBufferEnabled,
        }),
        room.connect(connectionDetails.serverUrl, connectionDetails.participantToken),
      ]).catch((error) => {
        if (aborted) {
          return;
        }

        toastAlert({
          title: 'There was an error connecting to the agent',
          description: `${error.name}: ${error.message}`,
        });
      });
    }
    return () => {
      aborted = true;
      if (room.state !== 'disconnected') {
        room.disconnect();
      }
    };
  }, [room, sessionStarted, connectionDetails, appConfig.isPreConnectBufferEnabled]);

  const handleEndSession = async () => {
    try {
      if (room.state !== 'disconnected') {
        await room.disconnect();
      }
    } finally {
      setSessionStarted(false);
      setMode(null);
    }
  };

  const { startButtonText } = appConfig;

  return (
    <>
      {isHydrated && !sessionStarted && (
        <MotionWelcome
          key="welcome"
          startButtonText={startButtonText}
          onStartLesson={() => {
            setMode('lesson');
          }}
          onStartCopilot={() => {
            setMode('copilot');
          }}
          disabled={sessionStarted}
          initial={{ opacity: 0 }}
          animate={{ opacity: sessionStarted ? 0 : 1 }}
          transition={{ duration: 0.5, ease: 'linear', delay: sessionStarted ? 0 : 0.5 }}
          // Ensure SSR matches intended visibility to avoid hydration flash
          style={{ opacity: sessionStarted ? 0 : 1, pointerEvents: sessionStarted ? 'none' : 'auto' }}
          aria-hidden={sessionStarted}
        />
      )}

      <RoomContext.Provider value={room}>
        <RoomAudioRenderer />
        <StartAudio label="Start Audio" />
        {/* --- */}
        <MotionSessionView
          key="session-view"
          appConfig={appConfig}
          mode={(mode ?? 'lesson') as Mode}
          disabled={!sessionStarted}
          sessionStarted={sessionStarted}
          onEndSession={handleEndSession}
          initial={{ opacity: 0 }}
          animate={{ opacity: sessionStarted ? 1 : 0 }}
          transition={{
            duration: 0.5,
            ease: 'linear',
            delay: sessionStarted ? 0.5 : 0,
          }}
          // Ensure SSR matches intended visibility to avoid hydration flash
          style={{ opacity: sessionStarted ? 1 : 0 }}
          aria-hidden={!sessionStarted}
        />
      </RoomContext.Provider>

      <Toaster />
    </>
  );
}
