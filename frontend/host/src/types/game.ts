export interface PlayerInfo {
  userId: string;
  displayName: string;
}

export interface SyncStatePayload {
  status: 'LOBBY' | 'IN_PROGRESS' | 'COMPLETED' | 'ABANDONED';
  players: PlayerInfo[];
  playerCount: number;
  questionPhase?: 'QUESTION' | 'RESULTS' | null;
  currentQuestion?: QuestionPayload | null;
  questionLocked?: boolean;
  timerRemainingSeconds?: number | null;
}

/** Sent to the room at game start, before the first new_question (T7). */
export interface GameImagesPayload {
  imageIds: string[];
}

export type QuestionType =
  | 'multiple_choice'
  | 'true_false'
  | 'fill_in_the_blank'
  | 'multi_select'
  | 'map_pin';

/** map_pin config: public by design (the target lives in answer_data, never sent). */
export interface MapPinConfig {
  imageId: string;
  imageWidth: number;
  imageHeight: number;
}

export interface QuestionConfig extends Partial<MapPinConfig> {
  options?: string[];
  maxLength?: number;
}

/** Same reveal for both grading types (spec §4.6). Radii in image-width units. */
export interface MapPinReveal {
  type: 'map_pin';
  gradingType: 'ACCURACY' | 'COMPLETENESS';
  imageId: string;
  imageWidth: number;
  imageHeight: number;
  target: { x: number; y: number };
  fullRadius: number;
  zeroRadius: number;
}

export interface PlayerJoinedPayload {
  userId: string;
  displayName: string;
  playerCount: number;
}

export interface PlayerLeftPayload {
  userId: string;
  playerCount: number;
}

export interface QuestionPayload {
  questionId: number;
  questionNumber: number;
  totalQuestions: number;
  type: QuestionType;
  gradingType: 'ACCURACY' | 'COMPLETENESS';
  prompt: string;
  config: QuestionConfig;
  timeLimitSeconds: number;
  pointsValue: number;
  editDistance?: number;
  startedAt?: string;  // ISO timestamp — only present in sync_state reconnect payloads
}

export interface AnswerStatusPayload {
  userId: string;
  displayName: string;
  answered: boolean;
  answeredCount: number;
  totalPlayers: number;
}

export interface AnswerPhaseEndedPayload {
  questionId: number;
  answeredCount: number;
  totalPlayers: number;
  allAnswered?: boolean; // true only when every player answered (not just timer expiry)
}

export interface LeaderboardEntry {
  userId: string;
  displayName: string;
  score: number;
  rank: number;
}

export type AnswerReveal =
  | { type: 'multiple_choice'; correctIndices: number[] }
  | { type: 'true_false'; correctValue: boolean }
  | { type: 'fill_in_the_blank'; acceptedAnswers: string[]; editDistance: number }
  | { type: 'completeness' }
  | { type: 'multi_select'; answerPoints: number[] }
  | MapPinReveal
  | Record<string, never>;

export interface HostResultsPayload {
  questionId: number;
  answerReveal: AnswerReveal;
  answerDistribution: Record<string, number>;
  totalAnswered: number;
  totalPlayers: number;
}

export interface HostQuestionSummaryItem {
  questionId: number;
  questionNumber: number;
  prompt: string;
  type: QuestionType;
  gradingType: 'ACCURACY' | 'COMPLETENESS';
  config: QuestionConfig;
  pointsValue: number;
  answerReveal: AnswerReveal;
  answerDistribution: Record<string, number>;
  totalAnswered: number;
  totalPlayers: number;
  correctCount: number;
  avgAnswerTimeMs: number | null;
  /** map_pin only, from geometry (both grading types); null when nobody answered. */
  withinFullPct?: number | null;
  averageCredit?: number | null;
}

export interface HostGameOverPayload {
  scores: number[];
  playerCount: number;
  maxPossibleScore: number;
  questionSummary: HostQuestionSummaryItem[];
}

export type HostPhase = 'lobby' | 'question' | 'results' | 'gameover';
