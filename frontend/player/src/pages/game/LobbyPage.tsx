import { useGame } from './GameLayout';
import { ThemeToggle } from '../../components/ThemeToggle';

export default function LobbyPage() {
  const { roomCode, playerCount, gameStatus } = useGame();

  const statusText = gameStatus === 'IN_PROGRESS'
    ? 'Waiting for next question…'
    : 'Waiting for host to start…';

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 gap-6 text-center pt-16">
      <ThemeToggle className="fixed top-3 right-3 z-40" />
      <div className="space-y-2">
        <p className="text-slate-400 text-sm uppercase tracking-widest">Room</p>
        <p className="text-4xl font-black font-mono tracking-widest text-white">{roomCode}</p>
      </div>

      <div className="mt-4 space-y-2">
        <div className="flex justify-center">
          <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
        </div>
        <p className="text-slate-300 text-lg font-medium">{statusText}</p>
        <p className="text-slate-500 text-sm">
          {playerCount} player{playerCount !== 1 ? 's' : ''} in room
        </p>
      </div>
    </div>
  );
}
