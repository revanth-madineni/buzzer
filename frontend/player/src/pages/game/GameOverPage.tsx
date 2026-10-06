import { useNavigate } from 'react-router-dom';
import { useGame } from './GameLayout';
import { Button } from '../../components/ui/button';
import type { PlayerAnswerReveal, QuestionSummaryItem } from '../../types/game';
import { ThemeToggle } from '../../components/ThemeToggle';
import { AuthImage } from '../../components/AuthImage';

function describePlayerAnswer(
  playerAnswer: { selectedIndex?: number; selectedValue?: boolean; text?: string; selectedIndices?: number[] } | null,
  type: string,
  options: string[] | undefined,
): string {
  if (!playerAnswer) return 'No answer';
  if (type === 'multiple_choice') {
    const idx = playerAnswer.selectedIndex;
    if (typeof idx === 'number' && options && options[idx] !== undefined) {
      return `${String.fromCharCode(65 + idx)} — ${options[idx]}`;
    }
    return '?';
  }
  if (type === 'true_false') {
    return playerAnswer.selectedValue ? 'True' : 'False';
  }
  if (type === 'fill_in_the_blank') {
    return typeof playerAnswer.text === 'string' ? playerAnswer.text : '—';
  }
  if (type === 'multi_select') {
    const indices = playerAnswer.selectedIndices;
    if (!indices || indices.length === 0) return 'No selection';
    if (options) return indices.map(i => `${String.fromCharCode(65 + i)} — ${options[i]}`).join(', ');
    return indices.map(i => String.fromCharCode(65 + i)).join(', ');
  }
  return '—';
}

function describeCorrectAnswer(
  answerReveal: PlayerAnswerReveal,
  options: string[] | undefined,
): string {
  if (answerReveal.type === 'multiple_choice') {
    const indices = answerReveal.correctIndices;
    if (options) {
      return indices.map(i => `${String.fromCharCode(65 + i)} — ${options[i]}`).join(', ');
    }
    return indices.map(i => String.fromCharCode(65 + i)).join(', ');
  }
  if (answerReveal.type === 'true_false') {
    return answerReveal.correctValue ? 'True' : 'False';
  }
  if (answerReveal.type === 'fill_in_the_blank') {
    const label = answerReveal.acceptedAnswers.join(' / ');
    return answerReveal.editDistance > 0 ? `${label} (±${answerReveal.editDistance})` : label;
  }
  if (answerReveal.type === 'multi_select') {
    const correct = answerReveal.answerPoints
      .map((p, i) => ({ p, i }))
      .filter(({ p }) => p > 0)
      .map(({ i }) => options ? `${String.fromCharCode(65 + i)} — ${options[i]}` : String.fromCharCode(65 + i));
    return correct.join(', ');
  }
  return '';
}

/** T8: option indices as letters, with a thumbnail for image options and text otherwise. */
function OptionChoices({ item, indices }: { item: QuestionSummaryItem; indices: number[] }) {
  const options = item.config.options ?? [];
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {indices.map((i) => {
        const imageId = item.config.optionImageIds?.[i] ?? null;
        return (
          <span key={i} className="inline-flex items-center gap-1">
            {String.fromCharCode(65 + i)}
            {imageId ? (
              <AuthImage imageId={imageId} alt={item.imageAlt?.[imageId] ?? ''} className="h-12 w-12" />
            ) : options[i] !== undefined ? (
              ` — ${options[i]}`
            ) : null}
          </span>
        );
      })}
    </span>
  );
}

/** Indices to draw as OptionChoices, or null to keep the plain text label. */
function imageChoiceIndices(item: QuestionSummaryItem, which: 'player' | 'correct'): number[] | null {
  if (!(item.config.optionImageIds ?? []).some((id) => !!id)) return null;
  if (which === 'player') {
    if (!item.playerAnswer) return null;
    if (item.type === 'multiple_choice' && typeof item.playerAnswer.selectedIndex === 'number') {
      return [item.playerAnswer.selectedIndex];
    }
    if (item.type === 'multi_select' && item.playerAnswer.selectedIndices?.length) {
      return item.playerAnswer.selectedIndices;
    }
    return null;
  }
  const reveal = item.answerReveal;
  if (reveal.type === 'multiple_choice') return reveal.correctIndices;
  if (reveal.type === 'multi_select') {
    return reveal.answerPoints.map((p, i) => (p > 0 ? i : -1)).filter((i) => i >= 0);
  }
  return null;
}

function QuestionRow({ item, index }: { item: QuestionSummaryItem; index: number }) {
  const options = item.config.options;
  const isCompleteness =
    item.answerReveal.type === 'completeness' ||
    (item.type === 'map_pin' && item.gradingType === 'COMPLETENESS');
  const noAnswer = !item.playerAnswer;
  const isCorrect = !isCompleteness && !noAnswer && item.pointsAwarded > 0;
  const showCorrectAnswer = !isCompleteness && !isCorrect;

  // map_pin recap: points earned / possible, no image (spec §4.10).
  const playerAnswerLabel =
    item.type === 'map_pin' && !noAnswer
      ? `${item.pointsAwarded.toLocaleString()} / ${item.maxPoints.toLocaleString()} pts`
      : describePlayerAnswer(item.playerAnswer, item.type, options);
  const correctAnswerLabel = !isCompleteness
    ? describeCorrectAnswer(item.answerReveal, options)
    : '';
  const playerImageChoices = imageChoiceIndices(item, 'player');
  const correctImageChoices = imageChoiceIndices(item, 'correct');

  return (
    <div className="bg-surface rounded-xl p-4 border border-line">
      <p className="text-fg-muted text-xs uppercase tracking-wider mb-1">Q{index + 1}</p>
      <p className="text-fg text-sm font-medium leading-snug mb-3">{item.prompt}</p>

      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-fg-muted text-xs mb-0.5">Your answer</p>
          <div className="flex items-center gap-2">
            {noAnswer ? (
              <span className="text-fg-muted text-base">—</span>
            ) : isCompleteness ? (
              <span className="text-accent-fg text-base">●</span>
            ) : isCorrect ? (
              <span className="text-success-fg text-base">✓</span>
            ) : (
              <span className="text-danger-fg text-base">✗</span>
            )}
            <span className={`text-sm font-semibold ${playerImageChoices ? '' : 'truncate'} ${
              noAnswer ? 'text-fg-muted' :
              isCompleteness ? 'text-accent-fg' :
              isCorrect ? 'text-success-fg' : 'text-danger-fg'
            }`}>
              {playerImageChoices ? (
                <OptionChoices item={item} indices={playerImageChoices} />
              ) : (
                playerAnswerLabel
              )}
            </span>
          </div>

          {showCorrectAnswer && correctImageChoices && correctImageChoices.length > 0 ? (
            <div className="text-fg-muted text-xs mt-1 flex items-center gap-2">
              Correct:
              <span className="text-success-fg font-medium">
                <OptionChoices item={item} indices={correctImageChoices} />
              </span>
            </div>
          ) : showCorrectAnswer && correctAnswerLabel && (
            <p className="text-fg-muted text-xs mt-1">
              Correct: <span className="text-success-fg font-medium">{correctAnswerLabel}</span>
            </p>
          )}
        </div>

        <div className="text-right shrink-0">
          <p className={`text-sm font-bold ${
            item.pointsAwarded > 0 ? 'text-success-fg' : 'text-fg-muted'
          }`}>
            +{item.pointsAwarded.toLocaleString()}
          </p>
          <p className="text-fg-muted text-xs">pts</p>
        </div>
      </div>
    </div>
  );
}

export default function GameOverPage() {
  const { gameOver } = useGame();
  const navigate = useNavigate();

  if (!gameOver) {
    return (
      <div className="min-h-screen flex items-center justify-center pt-16">
        <ThemeToggle className="fixed top-3 right-3 z-40" />
        <p className="text-fg-muted">Loading final results…</p>
      </div>
    );
  }

  const { yourFinalScore, yourFinalRank, playerCount, questionSummary } = gameOver;

  return (
    <div className="min-h-screen flex flex-col p-4 gap-5 pt-16">
      <ThemeToggle className="fixed top-3 right-3 z-40" />
      <div className="text-center pt-4 pb-2">
        <h1 className="text-4xl font-black text-fg">Game Over!</h1>
        <div className="mt-3 flex items-baseline justify-center gap-3">
          <span className="text-5xl font-black text-accent-fg">#{yourFinalRank}</span>
          <span className="text-fg-muted text-lg">of {playerCount}</span>
        </div>
        <p className="text-fg text-2xl font-bold mt-1">
          {yourFinalScore.toLocaleString()} pts
        </p>
      </div>

      <div className="flex flex-col gap-3 pb-4">
        <p className="text-fg-muted text-xs uppercase tracking-widest text-center">Question Recap</p>
        {questionSummary.map((item, i) => (
          <QuestionRow key={item.questionId} item={item} index={i} />
        ))}
      </div>

      <div className="pb-6 flex justify-center">
        <Button
          variant="outline"
          onClick={() => {
            localStorage.removeItem('token');
            navigate('/join');
          }}
        >
          Play Again
        </Button>
      </div>
    </div>
  );
}
