import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { Outlet, useNavigate, useParams } from 'react-router-dom';
import { isTokenExpired } from '../../lib/utils';
import { preloadImages } from '../../lib/images';
import { io, Socket } from 'socket.io-client';
import type {
  AnswerResultPayload,
  ErrorPayload,
  GameImagesPayload,
  PlayerGameOverPayload,
  PlayerJoinedPayload,
  PlayerPhase,
  PlayerResultsPayload,
  QuestionPayload,
  SyncStatePayload,
} from '../../types/game';

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

/**
 * Late-answer rejections (an honest Confirm/tap in the last moments of a question).
 * They don't end the game view; every other error still does.
 */
const NON_FATAL_ERROR_CODES = new Set(['NO_ACTIVE_QUESTION', 'QUESTION_LOCKED', 'QUESTION_MISMATCH']);
const REJECTED_BANNER_MS = 3000;

/** sessionStorage key for a player's accepted map pin, so results survive a reload. */
export function pinStorageKey(code: string, questionId: number): string {
  return `buzzer:pin:${code}:${questionId}`;
}

interface GameContextValue {
  phase: PlayerPhase;
  gameStatus: 'LOBBY' | 'IN_PROGRESS';
  roomCode: string;
  playerCount: number;
  hostDisconnected: boolean;
  currentQuestion: QuestionPayload | null;
  questionLocked: boolean;
  lastAnswerData: Record<string, unknown> | null;
  answerResult: AnswerResultPayload | null;
  questionResults: PlayerResultsPayload | null;
  gameOver: PlayerGameOverPayload | null;
  /** The last answer was rejected for timing; reset by new_question. */
  answerRejected: boolean;
  emitAnswer: (questionId: number, answerData: Record<string, unknown>, answerTimeMs: number) => void;
}

const GameContext = createContext<GameContextValue | null>(null);

export function useGame(): GameContextValue {
  const ctx = useContext(GameContext);
  if (!ctx) throw new Error('useGame must be used within GameLayout');
  return ctx;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export default function GameLayout() {
  const { code = '' } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const socketRef = useRef<Socket | null>(null);
  // Ref mirrors phase so socket event closures (registered once) can read current value.
  const phaseRef = useRef<PlayerPhase>('lobby');
  // What was last submitted, for the answer_received handler (registered once).
  const pendingAnswerRef = useRef<{ question: QuestionPayload; answer: Record<string, unknown> } | null>(null);
  const bannerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [phase, setPhase] = useState<PlayerPhase>('lobby');
  const [gameStatus, setGameStatus] = useState<'LOBBY' | 'IN_PROGRESS'>('LOBBY');
  const [playerCount, setPlayerCount] = useState(0);
  const [hostDisconnected, setHostDisconnected] = useState(false);
  const [currentQuestion, setCurrentQuestion] = useState<QuestionPayload | null>(null);
  const [questionLocked, setQuestionLocked] = useState(false);
  const [lastAnswerData, setLastAnswerData] = useState<Record<string, unknown> | null>(null);
  const [answerResult, setAnswerResult] = useState<AnswerResultPayload | null>(null);
  const [questionResults, setQuestionResults] = useState<PlayerResultsPayload | null>(null);
  const [gameOver, setGameOver] = useState<PlayerGameOverPayload | null>(null);
  const [answerRejected, setAnswerRejected] = useState(false);
  const [showRejectedBanner, setShowRejectedBanner] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token || isTokenExpired(token)) {
      localStorage.removeItem('token');
      navigate(code ? `/name/${code}` : '/join', { replace: true });
      return;
    }
    if (!code) {
      navigate('/join', { replace: true });
      return;
    }

    const sock = io({
      path: '/socket.io',
      auth: (cb) => cb({ token: localStorage.getItem('token') ?? '' }),
      transports: ['websocket', 'polling'],
    });
    socketRef.current = sock;

    sock.on('connect', () => {
      setError('');
      if (phaseRef.current !== 'gameover') {
        sock.emit('join_room', { room_code: code, role: 'PLAYER' });
      }
    });

    sock.on('connect_error', (err) => {
      if (phaseRef.current !== 'gameover') {
        setError(`Connection error: ${err.message}`);
      }
    });

    sock.on('sync_state', (data: SyncStatePayload) => {
      setPlayerCount(data.playerCount ?? 0);
      if (data.questionLocked) setQuestionLocked(true);
      if (data.imageIds) preloadImages(data.imageIds);
      if (data.status === 'LOBBY') {
        setGameStatus('LOBBY');
        setPhase('lobby');
        navigate(`/game/${code}/lobby`, { replace: true });
      } else if (data.status === 'IN_PROGRESS') {
        // Game already running — update state but don't navigate; new_question
        // (or question_results) will drive routing to the correct page.
        setGameStatus('IN_PROGRESS');
      }
    });

    sock.on('game_images', (data: GameImagesPayload) => {
      preloadImages(data.imageIds ?? []);
    });

    sock.on('player_joined', (data: PlayerJoinedPayload) => {
      setPlayerCount(data.playerCount);
    });

    sock.on('new_question', (data: QuestionPayload) => {
      setCurrentQuestion(data);
      setQuestionLocked(false);
      setLastAnswerData(null);
      setAnswerResult(null);
      setQuestionResults(null);
      setAnswerRejected(false);
      setHostDisconnected(false);
      setPhase('question');
      navigate(`/game/${code}/question`);
    });

    sock.on('question_locked', () => {
      setQuestionLocked(true);
    });

    sock.on('question_unlocked', () => {
      setQuestionLocked(false);
    });

    sock.on('answer_received', (data: AnswerResultPayload) => {
      if (data.alreadyAnswered) return; // ignore duplicate-submit echo
      const pending = pendingAnswerRef.current;
      if (pending?.question.type === 'map_pin' && pending.question.questionId === data.questionId) {
        // Accepted by the server: keep the pin so results can show it after a reload.
        try {
          sessionStorage.setItem(pinStorageKey(code, data.questionId), JSON.stringify(pending.answer));
        } catch {
          // Storage blocked or full: results just won't survive a reload.
        }
      }
      setAnswerResult(data);
      setPhase('feedback');
      navigate(`/game/${code}/feedback`);
    });

    sock.on('question_results', (data: PlayerResultsPayload) => {
      setQuestionResults(data);
      setPhase('results');
      navigate(`/game/${code}/results`);
    });

    sock.on('game_over', (data: PlayerGameOverPayload) => {
      phaseRef.current = 'gameover';
      setGameOver(data);
      setPhase('gameover');
      navigate(`/game/${code}/gameover`);
      sock.disconnect();
    });

    sock.on('host_disconnected', () => {
      setHostDisconnected(true);
    });

    sock.on('game_abandoned', () => {
      navigate('/join', { replace: true });
    });

    sock.on('error', (data: ErrorPayload) => {
      if (phaseRef.current === 'gameover') return;
      if (data.code && NON_FATAL_ERROR_CODES.has(data.code)) {
        // Too late, not broken: stay on the current view; the host's next
        // new_question / question_results moves the player on as usual.
        setAnswerRejected(true);
        setShowRejectedBanner(true);
        if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current);
        bannerTimerRef.current = setTimeout(() => setShowRejectedBanner(false), REJECTED_BANNER_MS);
        return;
      }
      setError(data.message);
    });

    return () => {
      sock.disconnect();
      socketRef.current = null;
      if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current);
    };
  }, [code, navigate]);

  function emitAnswer(questionId: number, answerData: Record<string, unknown>, answerTimeMs: number) {
    setLastAnswerData(answerData);
    if (currentQuestion) pendingAnswerRef.current = { question: currentQuestion, answer: answerData };
    socketRef.current?.emit('submit_answer', { question_id: questionId, answer_data: answerData, answer_time_ms: answerTimeMs });
  }

  if (error && phase !== 'gameover') {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="text-center space-y-4">
          <p className="text-red-400 text-lg">{error}</p>
          <button className="text-indigo-400 underline" onClick={() => navigate('/join')}>
            Back to Join
          </button>
        </div>
      </div>
    );
  }

  return (
    <GameContext.Provider
      value={{ phase, gameStatus, roomCode: code, playerCount, hostDisconnected, currentQuestion, questionLocked, lastAnswerData, answerResult, questionResults, gameOver, answerRejected, emitAnswer }}
    >
      {hostDisconnected && phase !== 'gameover' && (
        <div className="fixed top-0 inset-x-0 bg-yellow-600/90 text-yellow-100 text-center py-2 text-sm z-50">
          Host disconnected — waiting for them to reconnect…
        </div>
      )}
      {showRejectedBanner && phase !== 'gameover' && (
        <div role="status" className="fixed bottom-4 inset-x-4 rounded-xl bg-amber-600/95 text-amber-50 text-center py-3 text-sm font-semibold z-50 shadow-lg">
          Too late — your answer wasn't recorded
        </div>
      )}
      <Outlet />
    </GameContext.Provider>
  );
}
