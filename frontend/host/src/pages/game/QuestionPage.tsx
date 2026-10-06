import { useEffect } from 'react';
import { useGame } from './GameLayout';
import { Button } from '../../components/ui/button';
import { TimerBar } from '../../components/ui/TimerBar';

export default function QuestionPage() {
  const { currentQuestion, answeredCount, playerCount, allAnswered, answerPhaseEnded, questionLocked, lockedTimerSeconds, autoAdvance, emitAdvance, emitLockQuestion } = useGame();

  useEffect(() => {
    if (!autoAdvance || !answerPhaseEnded) return;
    const id = setTimeout(emitAdvance, 1500);
    return () => clearTimeout(id);
  }, [autoAdvance, answerPhaseEnded, emitAdvance]);

  if (!currentQuestion) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-fg-muted">Loading question…</p>
      </div>
    );
  }

  const typeLabel: Record<string, string> = {
    multiple_choice: 'Multiple Choice',
    true_false: 'True / False',
    fill_in_the_blank: 'Fill in the Blank',
    multi_select: 'Multi-Select',
    map_pin: 'Map Pin',
  };

  function editDistanceLabel(d: number): string {
    if (d === 0) return 'Exact spelling required';
    if (d === 1) return 'Up to 1 typo allowed';
    return `Up to ${d} typos allowed`;
  }

  const remainingSeconds = questionLocked && lockedTimerSeconds !== null
    ? lockedTimerSeconds
    : currentQuestion.startedAt
      ? Math.max(0, currentQuestion.timeLimitSeconds - (Date.now() - new Date(currentQuestion.startedAt).getTime()) / 1000)
      : currentQuestion.timeLimitSeconds;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-8 gap-8">
      <div className="flex items-center gap-3 text-sm uppercase tracking-wider">
        <span className="text-fg-muted">
          Question {currentQuestion.questionNumber} of {currentQuestion.totalQuestions}
        </span>
        <span className="text-fg-muted">·</span>
        <span className="text-fg-muted">{typeLabel[currentQuestion.type] ?? currentQuestion.type}</span>
        <span className="text-fg-muted">·</span>
        <span className={currentQuestion.gradingType === 'COMPLETENESS' ? 'text-warning-fg' : 'text-accent-fg'}>
          {currentQuestion.gradingType === 'COMPLETENESS' ? 'Participation' : 'Accuracy'}
        </span>
        {currentQuestion.type === 'fill_in_the_blank' && currentQuestion.gradingType === 'ACCURACY' && (
          <>
            <span className="text-fg-muted">·</span>
            <span className="text-fg-muted normal-case">
              {editDistanceLabel(currentQuestion.editDistance ?? 0)}
            </span>
          </>
        )}
      </div>

      <div className="w-full max-w-3xl">
        <TimerBar
          key={currentQuestion.questionId}
          totalSeconds={currentQuestion.timeLimitSeconds}
          initialSeconds={remainingSeconds}
          paused={questionLocked}
        />
      </div>

      {/* map_pin: the projector shows only the prompt; the map is on the phones. */}
      {!questionLocked && (
        <h2 className="text-4xl font-bold text-fg text-center max-w-3xl leading-tight">
          {currentQuestion.prompt}
        </h2>
      )}

      <div className="text-fg text-xl">
        {answeredCount} / {playerCount} answered
        {allAnswered && <span className="ml-3 text-success-fg font-semibold">All answered!</span>}
        {questionLocked && <span className="ml-3 text-warning-fg font-semibold">· Answers locked</span>}
      </div>

      <div className="flex gap-4">
        <Button
          size="lg"
          variant="outline"
          onClick={emitLockQuestion}
          className={`px-10 ${questionLocked ? 'border-warning text-warning-fg enabled:hover:bg-warning-soft' : ''}`}
        >
          {questionLocked ? 'Unlock Question' : 'Lock Question'}
        </Button>
        <Button size="lg" onClick={emitAdvance} className="px-10">
          Show Results
        </Button>
      </div>
    </div>
  );
}
