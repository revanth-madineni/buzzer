import { useEffect, useState } from 'react';
import { useGame } from './GameLayout';
import { Button } from '../../components/ui/button';
import { MapPinHeatmap } from '../../components/MapPinHeatmap';
import { SliderHistogram } from '../../components/SliderHistogram';
import { AuthImage } from '../../components/AuthImage';
import type { AnswerReveal, QuestionConfig } from '../../types/game';

const RESULTS_DISPLAY_SECONDS = 10;

function optionLabel(i: number): string {
  return String.fromCharCode(65 + i);
}

// ---------------------------------------------------------------------------
// Levenshtein distance — used to colour word-cloud entries for FITB questions
// ---------------------------------------------------------------------------

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, (_, i) =>
    Array.from({ length: n + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0))
  );
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

// ---------------------------------------------------------------------------
// Word Cloud — for fill_in_the_blank questions
// ---------------------------------------------------------------------------

interface WordCloudProps {
  distribution: Record<string, number>;
  answerReveal: AnswerReveal;
  totalAnswered: number;
  totalPlayers: number;
}

function WordCloud({ distribution, answerReveal, totalAnswered, totalPlayers }: WordCloudProps) {
  const entries = Object.entries(distribution).sort(([, a], [, b]) => b - a);
  const maxCount = Math.max(...entries.map(([, c]) => c), 1);

  const isAccuracy =
    'type' in answerReveal && answerReveal.type === 'fill_in_the_blank';
  const acceptedAnswers: string[] =
    isAccuracy && 'acceptedAnswers' in answerReveal
      ? (answerReveal as { type: 'fill_in_the_blank'; acceptedAnswers: string[]; editDistance: number }).acceptedAnswers.map(a => a.toLowerCase())
      : [];
  const editDistance: number =
    isAccuracy && 'editDistance' in answerReveal
      ? (answerReveal as { type: 'fill_in_the_blank'; acceptedAnswers: string[]; editDistance: number }).editDistance
      : 0;

  // [size, weight] by share of answers; the smallest is text-xl, readable on the projector.
  function sizeClass(count: number): [string, string] {
    const f = count / maxCount;
    if (f > 0.75) return ['text-5xl', 'font-black'];
    if (f > 0.5)  return ['text-4xl', 'font-bold'];
    if (f > 0.25) return ['text-3xl', 'font-semibold'];
    if (f > 0.1)  return ['text-2xl', 'font-medium'];
    return ['text-xl', ''];
  }

  function isCorrectWord(word: string): boolean {
    if (!isAccuracy || acceptedAnswers.length === 0) return false;
    return acceptedAnswers.some(a => levenshtein(word.toLowerCase(), a) <= editDistance);
  }

  return (
    <div className="w-full max-w-3xl flex flex-col gap-4">
      {isAccuracy && acceptedAnswers.length > 0 && (
        <p className="text-center text-fg text-lg">
          Correct answer:{' '}
          <span className="text-success-fg font-semibold">
            {(answerReveal as { acceptedAnswers: string[] }).acceptedAnswers.join(' / ')}
            {editDistance > 0 && (
              <span className="text-fg font-normal ml-1">(±{editDistance})</span>
            )}
          </span>
        </p>
      )}

      <div className="flex flex-wrap gap-x-5 gap-y-3 justify-center items-center min-h-32 p-4 bg-surface rounded-2xl">
        {entries.map(([word, count]) => {
          const [size, weight] = sizeClass(count);
          // Accepted words carry a ✓ and at least bold weight, so colour isn't the only cue.
          const accepted = isCorrectWord(word);
          return (
            <span
              key={word}
              title={`${count} player${count !== 1 ? 's' : ''}`}
              className={`${size} transition-colors ${
                accepted ? `text-success-fg ${weight === 'font-black' ? weight : 'font-bold'}` : `text-fg ${weight}`
              }`}
            >
              {accepted && '✓ '}
              {word}
            </span>
          );
        })}
        {entries.length === 0 && (
          <p className="text-fg text-lg">No answers submitted</p>
        )}
      </div>

      <p className="text-fg text-lg text-right">
        {totalAnswered} / {totalPlayers} answered
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bar Chart — for multiple_choice and true_false
// ---------------------------------------------------------------------------

interface BarChartProps {
  /** T8: an image option has `imageId` (label is then just the letter) and its alt text. */
  bars: { label: string; count: number; correct: boolean | null; imageId?: string | null; alt?: string }[];
  totalAnswered: number;
  totalPlayers: number;
}

function AnswerBarChart({ bars, totalAnswered, totalPlayers }: BarChartProps) {
  const maxCount = Math.max(...bars.map(b => b.count), 1);
  // When any option is correct, every row reserves the "✓ Correct" column, so all tracks are
  // the same length and the bars stay comparable.
  const anyCorrect = bars.some(b => b.correct === true);

  return (
    <div className="w-full max-w-4xl space-y-3">
      {bars.map((bar, i) => {
        const pct = Math.round((bar.count / maxCount) * 100);
        const barColor = bar.correct === true ? 'bg-chart-correct' : 'bg-chart-bar';

        // No text inside the bar: the count and "✓ Correct" sit beside it, on the page.
        return (
          <div key={i} className="flex items-center gap-4">
            {bar.imageId ? (
              <span className="w-64 shrink-0 flex items-center justify-end gap-3 text-fg text-xl font-bold">
                {bar.label}
                <AuthImage imageId={bar.imageId} alt={bar.alt ?? ''} className="h-16 w-16" />
              </span>
            ) : (
              <span className="w-64 shrink-0 text-right text-fg text-xl font-bold break-words">
                {bar.label}
              </span>
            )}
            <div className="flex-1 bg-chart-track rounded-full h-10 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                style={{ width: `${Math.max(pct, bar.count > 0 ? 4 : 0)}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-fg text-lg font-bold tabular-nums">
              {bar.count}
            </span>
            {anyCorrect && (
              <span className="w-28 shrink-0 text-success-fg text-lg font-semibold">
                {bar.correct === true ? '✓ Correct' : ''}
              </span>
            )}
          </div>
        );
      })}

      <p className="text-fg text-lg text-right pt-1">
        {totalAnswered} / {totalPlayers} answered
      </p>
    </div>
  );
}

function buildBars(
  reveal: AnswerReveal,
  distribution: Record<string, number>,
  config: QuestionConfig | undefined,
  imageAlt: Record<string, string> | undefined,
): BarChartProps['bars'] {
  const options = config?.options;
  // T8: an image option's text is "", so its label is the letter plus a thumbnail.
  const optionBar = (opt: string, i: number) => {
    const imageId = config?.optionImageIds?.[i] ?? null;
    return imageId
      ? { label: optionLabel(i), imageId, alt: imageAlt?.[imageId] ?? '' }
      : { label: `${optionLabel(i)}  ${opt}` };
  };

  if (reveal.type === 'multiple_choice') {
    const opts = options ?? [];
    return opts.map((opt, i) => ({
      ...optionBar(opt, i),
      count: distribution[String(i)] ?? 0,
      correct: reveal.correctIndices.includes(i),
    }));
  }

  if (reveal.type === 'multi_select') {
    const opts = options ?? [];
    return opts.map((opt, i) => ({
      ...optionBar(opt, i),
      count: distribution[String(i)] ?? 0,
      correct: (reveal.answerPoints[i] ?? 0) > 0,
    }));
  }

  if (reveal.type === 'true_false') {
    return [
      { label: 'True', count: distribution['true'] ?? 0, correct: reveal.correctValue === true },
      { label: 'False', count: distribution['false'] ?? 0, correct: reveal.correctValue === false },
    ];
  }

  // completeness (non-FITB) — no right/wrong
  if (options && options.length > 0) {
    return options.map((opt, i) => ({
      ...optionBar(opt, i),
      count: distribution[String(i)] ?? 0,
      correct: null,
    }));
  }

  if ('true' in distribution || 'false' in distribution) {
    return [
      { label: 'True', count: distribution['true'] ?? 0, correct: null },
      { label: 'False', count: distribution['false'] ?? 0, correct: null },
    ];
  }

  return [];
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ResultsPage() {
  const { questionResults, currentQuestion, autoAdvance, emitAdvance } = useGame();
  const [countdown, setCountdown] = useState(RESULTS_DISPLAY_SECONDS);

  const isLast = currentQuestion
    ? currentQuestion.questionNumber >= currentQuestion.totalQuestions
    : false;

  useEffect(() => {
    if (!autoAdvance) return;
    setCountdown(RESULTS_DISPLAY_SECONDS);
    const interval = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) { clearInterval(interval); emitAdvance(); return 0; }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [autoAdvance, questionResults, emitAdvance]);

  const isFitb = currentQuestion?.type === 'fill_in_the_blank';
  const mapReveal =
    questionResults?.answerReveal.type === 'map_pin' ? questionResults.answerReveal : null;

  const sliderReveal =
    questionResults?.answerReveal.type === 'slider' ? questionResults.answerReveal : null;

  const bars =
    !isFitb && !mapReveal && !sliderReveal && questionResults
      ? buildBars(
          questionResults.answerReveal,
          questionResults.answerDistribution,
          currentQuestion?.config,
          currentQuestion?.imageAlt,
        )
      : [];

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-8 gap-8">
      <h2 className="text-3xl font-bold text-fg">
        Question {currentQuestion?.questionNumber} Results
      </h2>

      {currentQuestion && (
        <p className="text-fg text-xl text-center max-w-2xl">
          {currentQuestion.prompt}
        </p>
      )}

      {questionResults && mapReveal ? (
        <div className="w-full max-w-4xl flex flex-col gap-2">
          <MapPinHeatmap reveal={mapReveal} distribution={questionResults.answerDistribution} />
          {mapReveal.gradingType === 'COMPLETENESS' && (
            <p className="text-center text-warning-fg text-lg">
              Participation — full credit for answering
            </p>
          )}
          <p className="text-fg text-lg text-right">
            {questionResults.totalAnswered} / {questionResults.totalPlayers} answered
          </p>
        </div>
      ) : questionResults && sliderReveal ? (
        <div className="w-full max-w-4xl flex flex-col gap-2">
          <SliderHistogram reveal={sliderReveal} distribution={questionResults.answerDistribution} />
          {sliderReveal.gradingType === 'COMPLETENESS' && (
            <p className="text-center text-warning-fg text-lg">
              Participation — full credit for answering
            </p>
          )}
          <p className="text-fg text-lg text-right">
            {questionResults.totalAnswered} / {questionResults.totalPlayers} answered
          </p>
        </div>
      ) : questionResults && isFitb ? (
        <WordCloud
          distribution={questionResults.answerDistribution}
          answerReveal={questionResults.answerReveal}
          totalAnswered={questionResults.totalAnswered}
          totalPlayers={questionResults.totalPlayers}
        />
      ) : questionResults ? (
        <AnswerBarChart
          bars={bars}
          totalAnswered={questionResults.totalAnswered}
          totalPlayers={questionResults.totalPlayers}
        />
      ) : null}

      <div className="flex flex-col items-center gap-2">
        <Button size="lg" onClick={emitAdvance} className="px-10">
          {isLast ? 'Show Final Results' : 'Next Question'}
        </Button>
        {autoAdvance && (
          <p className="text-fg-muted text-sm tabular-nums">
            Auto-advancing in {countdown}s
          </p>
        )}
      </div>
    </div>
  );
}
