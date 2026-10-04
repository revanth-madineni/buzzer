import { pinStorageKey, useGame } from './GameLayout';
import { MapPinCanvas } from '../../components/MapPinCanvas';
import { mapPinDistance, type Point } from '../../lib/mapPin';
import type { MapPinReveal, PlayerResultsPayload } from '../../types/game';

function asPin(value: unknown): Point | null {
  if (!value || typeof value !== 'object') return null;
  const { x, y } = value as { x?: unknown; y?: unknown };
  return typeof x === 'number' && typeof y === 'number' ? { x, y } : null;
}

function storedPin(code: string, questionId: number): Point | null {
  try {
    const raw = sessionStorage.getItem(pinStorageKey(code, questionId));
    return raw ? asPin(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

/** Label from geometry, so it matches the map whatever the points were (spec §4.10). */
function mapPinLabel(reveal: MapPinReveal, pin: Point | null): { text: string; className: string } {
  if (!pin) return { text: 'No answer', className: 'text-slate-400' };
  const d = mapPinDistance(reveal.imageWidth, reveal.imageHeight, reveal.target, pin);
  if (d <= reveal.fullRadius) return { text: 'Within target', className: 'text-green-400' };
  if (d < reveal.zeroRadius) return { text: 'Partial credit', className: 'text-amber-400' };
  return { text: 'Too far', className: 'text-red-400' };
}

function MapPinResults({
  results,
  reveal,
  pin,
}: {
  results: PlayerResultsPayload;
  reveal: MapPinReveal;
  pin: Point | null;
}) {
  const label = mapPinLabel(reveal, pin);
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-4 gap-4 text-center">
      <p className={`text-3xl font-black ${label.className}`}>
        {label.text}
        {reveal.gradingType === 'COMPLETENESS' && (
          <span className="block text-base font-semibold text-indigo-300 mt-1">
            · full credit for answering
          </span>
        )}
      </p>
      <div className="w-full">
        <MapPinCanvas
          imageId={reveal.imageId}
          imageWidth={reveal.imageWidth}
          imageHeight={reveal.imageHeight}
          reveal={reveal}
          myPin={pin}
        />
      </div>
      <p className="text-slate-100 text-3xl font-bold">+{results.yourPoints.toLocaleString()} pts</p>
      <div className="space-y-1">
        <p className="text-slate-300 text-lg">
          Total: <span className="font-bold text-white">{results.yourScore.toLocaleString()}</span> pts
        </p>
        <p className="text-slate-400 text-base">
          Rank <span className="font-bold text-white">#{results.yourRank}</span> of {results.playerCount}
        </p>
      </div>
      <p className="text-slate-500 text-sm mt-2">Waiting for next question…</p>
    </div>
  );
}

function describeAnswer(
  lastAnswerData: Record<string, unknown> | null,
  type: string,
  options: string[] | undefined,
): string | null {
  if (!lastAnswerData) return null;
  if (type === 'multiple_choice') {
    const idx = lastAnswerData.selectedIndex;
    if (typeof idx === 'number' && options && options[idx] !== undefined) {
      return `${String.fromCharCode(65 + idx)} — ${options[idx]}`;
    }
  }
  if (type === 'true_false') {
    return lastAnswerData.selectedValue ? 'True' : 'False';
  }
  if (type === 'fill_in_the_blank') {
    return typeof lastAnswerData.text === 'string' ? lastAnswerData.text : null;
  }
  return null;
}

export default function ResultsPage() {
  const { questionResults, currentQuestion, lastAnswerData, answerRejected, roomCode } = useGame();

  if (!questionResults) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-slate-400">Loading results…</p>
      </div>
    );
  }

  const { answerReveal, yourPoints, yourScore, yourRank, playerCount } = questionResults;

  if (answerReveal.type === 'map_pin') {
    // Own pin: this page's state, else the copy saved when the server accepted it.
    const local = currentQuestion?.questionId === questionResults.questionId ? asPin(lastAnswerData) : null;
    const pin = answerRejected ? null : local ?? storedPin(roomCode, questionResults.questionId);
    return <MapPinResults results={questionResults} reveal={answerReveal} pin={pin} />;
  }
  const answeredLabel = describeAnswer(
    lastAnswerData,
    currentQuestion?.type ?? '',
    currentQuestion?.config.options,
  );
  const isCompleteness = answerReveal.type === 'completeness';
  const isFitb = answerReveal.type === 'fill_in_the_blank';
  const isCorrect = !isCompleteness && yourPoints > 0;

  const fitbAccepted: string[] =
    isFitb && 'acceptedAnswers' in answerReveal ? answerReveal.acceptedAnswers : [];

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 gap-5 text-center">

      {/* Correct / Wrong / Recorded */}
      {isCompleteness ? (
        <p className="text-indigo-400 text-4xl font-black">Answer recorded!</p>
      ) : isCorrect ? (
        <p className="text-green-400 text-4xl font-black">Correct!</p>
      ) : (
        <p className="text-red-400 text-4xl font-black">Incorrect</p>
      )}

      {/* What the player answered */}
      {answeredLabel && (
        <p className="text-slate-400 text-base">
          You answered: <span className="text-slate-200 font-semibold">{answeredLabel}</span>
        </p>
      )}

      {/* Correct answer for FITB ACCURACY */}
      {isFitb && fitbAccepted.length > 0 && (
        <p className="text-slate-400 text-base">
          Correct: <span className="text-green-400 font-semibold">{fitbAccepted.join(' / ')}</span>
        </p>
      )}

      {/* Points for this question */}
      <p className="text-slate-100 text-3xl font-bold">
        +{yourPoints.toLocaleString()} pts
      </p>

      {/* Running total and rank */}
      <div className="mt-2 space-y-1">
        <p className="text-slate-300 text-lg">
          Total: <span className="font-bold text-white">{yourScore.toLocaleString()}</span> pts
        </p>
        <p className="text-slate-400 text-base">
          Rank <span className="font-bold text-white">#{yourRank}</span> of {playerCount}
        </p>
      </div>

      <p className="text-slate-500 text-sm mt-4">Waiting for next question…</p>
    </div>
  );
}
