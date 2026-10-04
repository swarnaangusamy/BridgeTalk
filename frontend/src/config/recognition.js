/**
 * Every recognition threshold, in one place.
 *
 * These were previously scattered between the Python smoother, the sequence
 * buffer and two React components, which is how they ended up disagreeing —
 * the reported "warm warm fast we we we we" was a time-based cooldown in one
 * file being the only guard against a classifier running in another.
 *
 * Measured values and the reasoning behind each are in PROGRESS.md. Change
 * them here and nowhere else.
 */

export const SIGN = {
  // --- accepting a prediction at all -------------------------------------
  // A softmax probability below this is not a sign; it is the model being
  // forced to answer about a hand that is resting. 40 classes means chance is
  // 2.5%, so 0.70 is a long way above "better than guessing".
  MIN_CONFIDENCE: 0.70,

  // The gap to the second-best class. Confidence alone is not enough: a model
  // can be 0.72 confident while the runner-up sits at 0.70, which means it
  // cannot really tell them apart. A clear margin is what stops near-ties
  // being committed as fact.
  MIN_MARGIN: 0.15,

  // --- movement segmentation ---------------------------------------------
  // Mean per-landmark displacement between consecutive frames, in normalised
  // units where a hand spans 1.0. Below this the hands are held still.
  REST_MOTION: 0.012,

  // Above this the hands are travelling, which is what a word sign IS.
  MOVING_MOTION: 0.030,

  // Consecutive still frames that end a movement segment. At 10 FPS this is
  // 0.4 s — long enough not to trigger on the brief pause inside a sign,
  // short enough that the caption does not lag behind the signer.
  REST_FRAMES_TO_END_SEGMENT: 4,

  // --- ending an utterance ------------------------------------------------
  // Hands absent or at rest for this long closes the caption segment and
  // sends the final event. 1.5 s, per the specification.
  UTTERANCE_END_MS: 1500,

  // --- letters -------------------------------------------------------------
  // A letter must hold steady for this many frames before it is committed.
  // Fingerspelling has no movement to segment on, so stability is the only
  // signal available.
  LETTER_STABLE_FRAMES: 6,

  // --- repeat suppression --------------------------------------------------
  // After committing a token, the same token is not committed again until the
  // hands have returned to rest. This replaces the old time-based cooldown,
  // which fired again the moment it expired even though the signer had not
  // moved — the direct cause of the repeated words.
  REQUIRE_REST_BEFORE_REPEAT: true,

  // Frames with no hands at all before a frame counts as genuinely empty.
  // One dropped detection mid-sign is noise, not an absence.
  ABSENT_FRAMES_TO_CLEAR: 3,

  // --- the parked-hand gate ------------------------------------------------
  // A letter must have been ARRIVED AT, not merely held. Within this many
  // frames there must have been real movement, or nothing is committed.
  //
  // Measured, and this is why it exists: fed a resting hand, the letter model
  // passes the confidence and margin gates essentially always — a hand at rest
  // IS a valid handshape, so the model is not wrong to be confident about it,
  // and no probability threshold can separate "resting in this shape" from
  // "signing this letter". Stability gating cannot help either: a parked hand
  // is perfectly stable.
  //
  // Movement is the only signal that distinguishes the two. 20 frames at
  // 10 FPS is 2 s, so a hand left in frame stops producing captions about two
  // seconds after it stops moving.
  MOTION_LOOKBACK_FRAMES: 20,
};

export const SPEECH = {
  // Web Speech restarts: bounded so a failing recogniser cannot busy-loop,
  // and refunded after a healthy run so a long meeting does not exhaust it.
  MAX_RESTARTS: 40,
  RESTART_BASE_MS: 300,
  RESTART_MAX_MS: 5000,
  HEALTHY_RUN_MS: 15000,
};
