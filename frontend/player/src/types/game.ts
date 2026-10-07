import type { SliderRevealData, SliderSettings } from '../lib/slider';

export interface SyncStatePayload {
  status: 'LOBBY' | 'IN_PROGRESS' | 'COMPLETED' | 'ABANDONED';
  playerCount: number;
  questionLocked?: boolean;
  /** Map images to preload (LOBBY / IN_PROGRESS only). May go stale in LOBBY. */
  imageIds?: string[];
}

/** Sent to the room at game start, before the first new_question. Final. */
export interface GameImagesPayload {
  imageIds: string[];
}

/**
 * `code` marks the three late-answer rejections, which are non-fatal; any other
 * error (no code) ends the game view.
 */
export interface ErrorPayload {
  message: string;
  code?: 'NO_ACTIVE_QUESTION' | 'QUESTION_LOCKED' | 'QUESTION_MISMATCH' | string;
}

export type QuestionType =
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_the_blank'
  | 'multi_select'
  | 'map_pin'
  | 'slider';

/** map_pin config: public by design (the target lives in answer_data, never sent). */
export interface MapPinConfig {
  imageId: string;
  imageWidth: number;
  imageHeight: number;
}

/** A map_pin answer: fractions of the image, x left→right, y top→bottom, in [0, 1]. */
export interface MapPinAnswer {
  x: number;
  y: number;
}

/** slider config (T7 slider spec §4.1): public; the target lives in answer_data. */
export type SliderConfig = SliderSettings;

/** A slider answer: the canonical value of the chosen step. */
export interface SliderAnswer {
  value: number;
}

export interface QuestionConfig extends Partial<MapPinConfig>, SliderConfig {
  options?: string[];
  maxLength?: number;
  /** T8: one image shown with the prompt (projector only); any question type. */
  promptImageId?: string;
  /** T8: multiple_choice / multi_select only; same length as `options`, null = text option. */
  optionImageIds?: (string | null)[];
}

/** T8: image ID → alt text, for every image the question references; omitted when none. */
export type ImageAltMap = Record<string, string>;

export interface PlayerJoinedPayload {
  playerCount: number;
}

export interface QuestionPayload {
  questionId: number;
  questionNumber: number;
  totalQuestions: number;
  type: QuestionType;
  prompt: string;
  config: QuestionConfig;
  timeLimitSeconds: number;
  pointsValue: number;
  imageAlt?: ImageAltMap;
}

export interface AnswerResultPayload {
  questionId: number;
  isCorrect: boolean;
  pointsAwarded: number;
  totalScore: number;
  alreadyAnswered?: boolean;
}

/** Same reveal for both grading types (spec §4.6). Radii in image-width units. */
export interface MapPinReveal {
  type: 'map_pin';
  gradingType: 'ACCURACY' | 'COMPLETENESS';
  imageId: string;
  imageWidth: number;
  imageHeight: number;
  target: MapPinAnswer;
  fullRadius: number;
  zeroRadius: number;
}

/** Same reveal for both grading types (slider spec §4.3). Radii are fractions of the range. */
export interface SliderReveal extends SliderRevealData {
  type: 'slider';
  gradingType: 'ACCURACY' | 'COMPLETENESS';
}

export type PlayerAnswerReveal =
  | { type: 'multiple_choice'; correctIndices: number[] }
  | { type: 'true_false'; correctValue: boolean }
  | { type: 'fill_in_the_blank'; acceptedAnswers: string[]; editDistance: number }
  | { type: 'completeness' }
  | { type: 'multi_select'; answerPoints: number[] }
  | MapPinReveal
  | SliderReveal;

export interface PlayerResultsPayload {
  questionId: number;
  answerReveal: PlayerAnswerReveal;
  yourPoints: number;
  yourScore: number;
  yourRank: number;
  playerCount: number;
}

export interface QuestionSummaryItem {
  questionId: number;
  prompt: string;
  type: QuestionType;
  gradingType: 'ACCURACY' | 'COMPLETENESS';
  config: QuestionConfig;
  pointsAwarded: number;
  maxPoints: number;
  answerTimeMs: number | null;
  playerAnswer: { selectedIndex?: number; selectedValue?: boolean; text?: string; selectedIndices?: number[]; x?: number; y?: number; value?: number } | null;
  answerReveal: PlayerAnswerReveal;
  imageAlt?: ImageAltMap;
}

export interface PlayerGameOverPayload {
  yourFinalScore: number;
  yourFinalRank: number;
  playerCount: number;
  questionSummary: QuestionSummaryItem[];
}

export type PlayerPhase = 'lobby' | 'question' | 'feedback' | 'results' | 'gameover';
