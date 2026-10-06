import { useRef, useState, useCallback, useEffect } from 'react';
import { useGame } from './GameLayout';
import { TimerBar } from '../../components/ui/TimerBar';
import { MapPinCanvas } from '../../components/MapPinCanvas';
import { AuthImage } from '../../components/AuthImage';
import { clampPoint, type Point } from '../../lib/mapPin';
import type { QuestionPayload } from '../../types/game';

const OPTION_COLORS = [
  'bg-answer-1 text-on-answer-1 border-answer-1',
  'bg-answer-2 text-on-answer-2 border-answer-2',
  'bg-answer-3 text-on-answer-3 border-answer-3',
  'bg-answer-4 text-on-answer-4 border-answer-4',
  'bg-answer-5 text-on-answer-5 border-answer-5',
  'bg-answer-6 text-on-answer-6 border-answer-6',
  'bg-answer-7 text-on-answer-7 border-answer-7',
  'bg-answer-8 text-on-answer-8 border-answer-8',
];

function optionLabel(i: number): string {
  return String.fromCharCode(65 + i); // A, B, C, … Z
}

/** T8: option i's image ID, or null for a text option. */
function optionImageId(question: QuestionPayload, i: number): string | null {
  return question.config.optionImageIds?.[i] ?? null;
}

/** T8: any image option switches the options to a 2-column grid of square buttons. */
function hasOptionImages(question: QuestionPayload): boolean {
  return (question.config.optionImageIds ?? []).some((id) => !!id);
}

/** The button carries the description, so the <img> inside it gets alt="" (not read twice). */
function imageOptionLabel(question: QuestionPayload, i: number, imageId: string): string {
  const alt = question.imageAlt?.[imageId] ?? '';
  return alt ? `Option ${optionLabel(i)}: ${alt}` : `Option ${optionLabel(i)}, image`;
}

/** Body of a grid cell under its letter badge: the image, or the option's text. */
function GridCellBody({ imageId, text }: { imageId: string | null; text: string }) {
  if (imageId) {
    return <AuthImage imageId={imageId} alt="" className="flex-1 min-h-0 w-full rounded-xl" />;
  }
  return (
    <span className="flex-1 min-h-0 flex items-center justify-center text-center break-words overflow-hidden">
      {text}
    </span>
  );
}

const rejectedMsg = (
  <p className="text-center text-warning-fg text-sm mt-4 font-semibold">
    Not recorded — time ran out
  </p>
);

/**
 * map_pin: tap to place, tap or drag to move, Confirm to submit (spec §4.10).
 * Keyed by questionId so a new question always starts with no pin. No auto-submit
 * at time-up: the server timer is authoritative and would usually reject it.
 */
function MapPinQuestion({
  question,
  startTime,
  header,
}: {
  question: QuestionPayload;
  startTime: number;
  header: React.ReactNode;
}) {
  const { questionLocked, answerRejected, emitAnswer } = useGame();
  const [pin, setPin] = useState<Point | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  // `submitted` is set before the server acknowledges; a timing rejection undoes it.
  useEffect(() => {
    if (answerRejected) setSubmitted(false);
  }, [answerRejected]);

  const { imageId, imageWidth, imageHeight } = question.config;
  if (!imageId || !imageWidth || !imageHeight) {
    return <p className="text-fg-muted text-center p-6">This question has no map.</p>;
  }

  const inactive = submitted || questionLocked || answerRejected;
  const canConfirm = !!pin && loaded && !inactive;

  return (
    <div className="py-6 px-4 flex flex-col gap-3">
      <div className="pb-2">{header}</div>
      <p className="text-center text-fg-muted text-sm">
        {pin ? 'Drag or tap to adjust, then confirm' : 'Tap the map to place your pin'}
      </p>
      <MapPinCanvas
        imageId={imageId}
        imageWidth={imageWidth}
        imageHeight={imageHeight}
        pin={pin}
        onPinChange={setPin}
        disabled={inactive}
        onLoadedChange={setLoaded}
      />
      {!inactive && (
        <button
          disabled={!canConfirm}
          onClick={() => {
            if (!pin || !canConfirm) return;
            const { x, y } = clampPoint(pin); // guard against rounding outside [0, 1]
            setSubmitted(true);
            emitAnswer(question.questionId, { x, y }, Date.now() - startTime);
          }}
          className="w-full rounded-2xl py-5 text-on-accent font-black text-2xl bg-accent enabled:hover:bg-accent-hover active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2"
        >
          Confirm
        </button>
      )}
      {submitted && <p className="text-center text-fg-muted text-sm mt-2">Pin submitted — waiting for results…</p>}
      {!submitted && answerRejected && rejectedMsg}
      {!submitted && !answerRejected && questionLocked && (
        <p className="text-center text-warning-fg text-sm mt-2 font-semibold">
          Answers locked — waiting for results…
        </p>
      )}
    </div>
  );
}

export default function QuestionPage() {
  const { currentQuestion, questionLocked, answerRejected, emitAnswer } = useGame();
  const startTimeRef = useRef(Date.now());
  const [submitted, setSubmitted] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());

  // `submitted` is set before the server acknowledges; a timing rejection undoes it.
  useEffect(() => {
    if (answerRejected) setSubmitted(false);
  }, [answerRejected]);

  const toggleIndex = useCallback((i: number) => {
    if (submitted || questionLocked || answerRejected) return;
    setSelectedIndices(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  }, [submitted, questionLocked, answerRejected]);

  if (!currentQuestion) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-fg-muted">Loading question…</p>
      </div>
    );
  }

  function submit(answerData: Record<string, unknown>) {
    if (submitted) return;
    setSubmitted(true);
    emitAnswer(currentQuestion!.questionId, answerData, Date.now() - startTimeRef.current);
  }

  const questionLabel = (
    <p className="text-fg-muted text-sm text-center tracking-wide uppercase mb-1">
      Question {currentQuestion.questionNumber} of {currentQuestion.totalQuestions}
    </p>
  );

  const lockedMsg = (
    <p className="text-center text-warning-fg text-sm mt-4 font-semibold">
      Answers locked — waiting for results…
    </p>
  );

  if (currentQuestion.type === 'multiple_choice') {
    const options = currentQuestion.config.options ?? [];
    return (
      <div className="py-6 px-4 flex flex-col gap-3">
        <div className="pb-2">
          {questionLabel}
          <TimerBar key={currentQuestion.questionId} totalSeconds={currentQuestion.timeLimitSeconds} paused={questionLocked} />
        </div>
        {hasOptionImages(currentQuestion) ? (
          <div className="grid grid-cols-2 gap-3">
            {options.map((opt, i) => {
              const imageId = optionImageId(currentQuestion, i);
              return (
                <button
                  key={i}
                  disabled={submitted || questionLocked || answerRejected}
                  onClick={() => submit({ selectedIndex: i })}
                  aria-label={imageId ? imageOptionLabel(currentQuestion, i, imageId) : undefined}
                  className={`aspect-square flex flex-col gap-1 rounded-2xl p-2 text-left font-semibold text-lg border-2 transition-all
                    ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}
                    ${OPTION_COLORS[i % OPTION_COLORS.length]}`}
                >
                  <span className="text-2xl font-black px-1 leading-none" aria-hidden={imageId ? true : undefined}>
                    {optionLabel(i)}
                  </span>
                  <GridCellBody imageId={imageId} text={opt} />
                </button>
              );
            })}
          </div>
        ) : (
          options.map((opt, i) => (
            <button
              key={i}
              disabled={submitted || questionLocked || answerRejected}
              onClick={() => submit({ selectedIndex: i })}
              className={`w-full flex items-center gap-4 rounded-2xl px-5 py-4 text-left font-semibold text-lg border-2 transition-all
                ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}
                ${OPTION_COLORS[i % OPTION_COLORS.length]}`}
            >
              <span className="text-2xl font-black w-8 shrink-0">{optionLabel(i)}</span>
              <span>{opt}</span>
            </button>
          ))
        )}
        {submitted && <p className="text-center text-fg-muted text-sm mt-4">Answer submitted — waiting for results…</p>}
        {!submitted && answerRejected && rejectedMsg}
        {!submitted && !answerRejected && questionLocked && lockedMsg}
      </div>
    );
  }

  if (currentQuestion.type === 'true_false') {
    return (
      <div className="min-h-screen flex flex-col justify-center p-4 gap-4">
        {questionLabel}
        <TimerBar key={currentQuestion.questionId} totalSeconds={currentQuestion.timeLimitSeconds} paused={questionLocked} />
        <button
          disabled={submitted || questionLocked || answerRejected}
          onClick={() => submit({ selectedValue: true })}
          className={`w-full rounded-2xl py-8 text-on-answer-4 font-black text-3xl border-2 border-answer-4 bg-answer-4 transition-all
            ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}`}
        >
          True
        </button>
        <button
          disabled={submitted || questionLocked || answerRejected}
          onClick={() => submit({ selectedValue: false })}
          className={`w-full rounded-2xl py-8 text-on-answer-1 font-black text-3xl border-2 border-answer-1 bg-answer-1 transition-all
            ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}`}
        >
          False
        </button>
        {submitted && <p className="text-center text-fg-muted text-sm mt-2">Answer submitted — waiting for results…</p>}
        {!submitted && answerRejected && rejectedMsg}
        {!submitted && !answerRejected && questionLocked && lockedMsg}
      </div>
    );
  }

  if (currentQuestion.type === 'fill_in_the_blank') {
    const maxLength = currentQuestion.config.maxLength ?? 100;
    return (
      <div className="min-h-screen flex flex-col justify-center p-4 gap-5">
        {questionLabel}
        <TimerBar key={currentQuestion.questionId} totalSeconds={currentQuestion.timeLimitSeconds} paused={questionLocked} />

        {submitted ? (
          <div className="flex flex-col items-center gap-3">
            <div className="text-5xl">🔒</div>
            <p className="text-fg text-xl font-bold">Answer locked in!</p>
            <p className="text-fg-muted text-base italic">"{inputValue.trim()}"</p>
            <p className="text-fg-muted text-sm mt-2">Waiting for results…</p>
          </div>
        ) : answerRejected ? (
          <div className="flex flex-col items-center gap-3 mt-4">
            {rejectedMsg}
          </div>
        ) : questionLocked ? (
          <div className="flex flex-col items-center gap-3 mt-4">
            {lockedMsg}
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const trimmed = inputValue.trim();
              if (trimmed) submit({ text: trimmed });
            }}
            className="flex flex-col gap-4"
          >
            <input
              type="text"
              maxLength={maxLength}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Type your answer…"
              autoFocus
              className="w-full rounded-xl px-4 py-4 border border-line-strong text-fg text-xl bg-surface"
            />
            <button
              type="submit"
              disabled={!inputValue.trim()}
              className="w-full rounded-2xl py-5 text-on-accent font-black text-2xl bg-accent enabled:hover:bg-accent-hover active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Submit
            </button>
          </form>
        )}
      </div>
    );
  }

  if (currentQuestion.type === 'multi_select') {
    const options = currentQuestion.config.options ?? [];
    return (
      <div className="py-6 px-4 flex flex-col gap-3">
        <div className="pb-2">
          {questionLabel}
          <TimerBar key={currentQuestion.questionId} totalSeconds={currentQuestion.timeLimitSeconds} paused={questionLocked} />
        </div>
        <p className="text-center text-fg-muted text-sm">Select all that apply</p>
        {hasOptionImages(currentQuestion) ? (
          <div className="grid grid-cols-2 gap-3">
            {options.map((opt, i) => {
              const isSelected = selectedIndices.has(i);
              const imageId = optionImageId(currentQuestion, i);
              return (
                <button
                  key={i}
                  disabled={submitted || questionLocked || answerRejected}
                  onClick={() => toggleIndex(i)}
                  aria-label={imageId ? imageOptionLabel(currentQuestion, i, imageId) : undefined}
                  aria-pressed={isSelected}
                  className={`aspect-square flex flex-col gap-1 rounded-2xl p-2 text-left font-semibold text-lg border-2 transition-all
                    ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}
                    ${isSelected
                      ? 'bg-accent border-on-accent text-on-accent'
                      : 'bg-surface border-line-strong text-fg enabled:hover:bg-surface-hover'
                    }`}
                >
                  <span className={`text-xl font-black w-8 h-8 shrink-0 flex items-center justify-center rounded-md border-2 transition-colors
                    ${isSelected ? 'border-on-accent bg-on-accent text-accent' : 'border-line-strong text-fg-muted'}`}>
                    {isSelected ? '✓' : optionLabel(i)}
                  </span>
                  <GridCellBody imageId={imageId} text={opt} />
                </button>
              );
            })}
          </div>
        ) : (
          options.map((opt, i) => {
            const isSelected = selectedIndices.has(i);
            return (
              <button
                key={i}
                disabled={submitted || questionLocked || answerRejected}
                onClick={() => toggleIndex(i)}
                className={`w-full flex items-center gap-4 rounded-2xl px-5 py-4 text-left font-semibold text-lg border-2 transition-all
                  ${submitted || questionLocked || answerRejected ? 'opacity-50 cursor-not-allowed' : 'active:scale-95'}
                  ${isSelected
                    ? 'bg-accent border-on-accent text-on-accent'
                    : 'bg-surface border-line-strong text-fg enabled:hover:bg-surface-hover'
                  }`}
              >
                <span className={`text-xl font-black w-8 shrink-0 flex items-center justify-center rounded-md border-2 transition-colors
                  ${isSelected ? 'border-on-accent bg-on-accent text-accent' : 'border-line-strong text-fg-muted'}`}>
                  {isSelected ? '✓' : optionLabel(i)}
                </span>
                <span>{opt}</span>
              </button>
            );
          })
        )}
        {!submitted && !questionLocked && !answerRejected && (
          <button
            disabled={selectedIndices.size === 0}
            onClick={() => submit({ selectedIndices: Array.from(selectedIndices) })}
            className="w-full rounded-2xl py-5 text-on-accent font-black text-2xl bg-accent enabled:hover:bg-accent-hover active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed mt-2"
          >
            Submit ({selectedIndices.size} selected)
          </button>
        )}
        {submitted && <p className="text-center text-fg-muted text-sm mt-4">Answer submitted — waiting for results…</p>}
        {!submitted && answerRejected && rejectedMsg}
        {!submitted && !answerRejected && questionLocked && lockedMsg}
      </div>
    );
  }

  if (currentQuestion.type === 'map_pin') {
    return (
      <MapPinQuestion
        key={currentQuestion.questionId}
        question={currentQuestion}
        startTime={startTimeRef.current}
        header={
          <>
            {questionLabel}
            <TimerBar key={currentQuestion.questionId} totalSeconds={currentQuestion.timeLimitSeconds} paused={questionLocked} />
          </>
        }
      />
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <p className="text-fg-muted">Unsupported question type.</p>
    </div>
  );
}
