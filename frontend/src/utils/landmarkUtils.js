/**
 * Landmark normalisation — the browser half of a two-language contract.
 *
 * THIS FILE MUST PRODUCE THE SAME NUMBERS AS
 * backend/app/ml/normalization.py, TO WITHIN 1e-6.
 *
 * Read that file first — it explains why normalisation exists at all. The
 * short version: raw MediaPipe coordinates depend on where the hand is in the
 * frame and how far it is from the camera, neither of which has anything to do
 * with which sign is being made. Normalisation strips both out.
 *
 * WHY THE SAME MATHS EXISTS IN TWO LANGUAGES
 * ------------------------------------------
 * The model is trained in Python and served from Python, so Python is the
 * authority. The browser needs its own copy because it draws the landmark
 * overlay and can optionally pre-normalise before sending.
 *
 * If these two implementations ever disagree, the failure is silent and
 * vicious: training accuracy stays at 97% while live predictions become noise,
 * with nothing in any log to point at the cause. backend/tests/
 * test_normalization_parity.py therefore runs identical inputs through both
 * implementations and fails the build if they diverge by more than 1e-6.
 *
 * If you change the maths here, change it there, and bump
 * NORMALIZATION_VERSION in both places.
 */

// Must match NORMALIZATION_VERSION in backend/app/ml/normalization.py.
export const NORMALIZATION_VERSION = 1;

export const NUM_LANDMARKS = 21;
export const COORDS_PER_LANDMARK = 3;
export const SINGLE_HAND_FEATURES = NUM_LANDMARKS * COORDS_PER_LANDMARK; // 63
export const TWO_HAND_FEATURES = SINGLE_HAND_FEATURES * 2; // 126

// Below this scale, every landmark sits on top of the wrist — a degenerate
// detection rather than a hand. Dividing by it would produce Infinity.
const MIN_SCALE = 1e-8;

/**
 * Normalise one hand's 21 landmarks into 63 floats.
 *
 * @param {Array<{x: number, y: number, z: number}> | Array<number[]>} landmarks
 *        21 points. Accepts MediaPipe's {x, y, z} objects or plain [x, y, z]
 *        arrays, because the former is what the browser gets and the latter is
 *        what crosses the WebSocket.
 * @returns {Float32Array} 63 values, wrist-centred and scale-normalised.
 *          All zeros for a degenerate hand.
 * @throws {Error} if the input is not 21 points. Deliberately strict: silently
 *         padding a malformed frame would let corrupt data reach the model.
 */
export function normalizeHand(landmarks) {
  if (!landmarks || landmarks.length !== NUM_LANDMARKS) {
    throw new Error(
      `Expected ${NUM_LANDMARKS} landmarks, got ${landmarks ? landmarks.length : 0}`,
    );
  }

  // Accept both shapes without branching further down.
  const points = landmarks.map((point) =>
    Array.isArray(point) ? point : [point.x, point.y, point.z ?? 0],
  );

  // --- 1. Translate: put the wrist (landmark 0) at the origin ---------------
  const [wristX, wristY, wristZ] = points[0];
  const centred = points.map(([x, y, z]) => [x - wristX, y - wristY, z - wristZ]);

  // --- 2. Scale: the furthest landmark from the wrist becomes 1.0 -----------
  let scale = 0;
  for (const [x, y, z] of centred) {
    const distance = Math.sqrt(x * x + y * y + z * z);
    if (distance > scale) scale = distance;
  }

  const features = new Float32Array(SINGLE_HAND_FEATURES);
  if (scale < MIN_SCALE) {
    return features; // all zeros
  }

  // --- 3. Flatten in fixed landmark order: x0,y0,z0, x1,y1,z1, … ------------
  // The order is fixed by MediaPipe's landmark indexing and must never be
  // re-sorted — the model learned this exact arrangement.
  let index = 0;
  for (const [x, y, z] of centred) {
    features[index] = x / scale;
    features[index + 1] = y / scale;
    features[index + 2] = z / scale;
    index += COORDS_PER_LANDMARK;
  }

  return features;
}

/**
 * Normalise a frame containing zero, one or two hands.
 *
 * @param {Array<{handedness: string, landmarks: any[]}>} hands
 * @returns {Float32Array} 126 values as [leftHand(63), rightHand(63)].
 *          A hand that is not present is zero-filled.
 *
 * Slotting by handedness rather than by detection order is what makes
 * two-handed signs learnable: MediaPipe returns hands in whatever order it
 * found them, so without this the same sign would land in different halves of
 * the vector from frame to frame.
 */
export function normalizeHands(hands) {
  const features = new Float32Array(TWO_HAND_FEATURES);
  if (!hands || hands.length === 0) return features;

  for (const hand of hands) {
    if (!hand || !hand.landmarks) continue;

    const handedness = String(hand.handedness ?? '').trim().toLowerCase();
    const offset = handedness.startsWith('l') ? 0 : SINGLE_HAND_FEATURES;

    features.set(normalizeHand(hand.landmarks), offset);
  }

  return features;
}

/**
 * Normalise the single most relevant hand, for the static (fingerspelling) model.
 *
 * ASL fingerspelling is one-handed, so Model A takes 63 features rather than
 * 126. When two hands are visible we prefer the right, matching the ASL
 * Alphabet dataset, which is overwhelmingly right-handed.
 *
 * @param {Array<{handedness: string, landmarks: any[]}>} hands
 * @returns {Float32Array} 63 values, all zeros if no hand is present.
 */
export function normalizePrimaryHand(hands) {
  if (!hands || hands.length === 0) {
    return new Float32Array(SINGLE_HAND_FEATURES);
  }

  const preferred =
    hands.find((hand) =>
      String(hand?.handedness ?? '').trim().toLowerCase().startsWith('r'),
    ) ?? hands[0];

  if (!preferred || !preferred.landmarks) {
    return new Float32Array(SINGLE_HAND_FEATURES);
  }

  return normalizeHand(preferred.landmarks);
}

/**
 * Convert MediaPipe's HandLandmarker result into the WebSocket wire format.
 *
 * Note what this sends: coordinates, and nothing else. No pixels, no frame, no
 * image data of any kind. That is the privacy claim of the whole architecture,
 * and this function is where it is either true or not.
 *
 * @param {object} result MediaPipe HandLandmarkerResult
 * @returns {Array<{handedness: string, landmarks: number[][]}>}
 */
export function toWireFormat(result) {
  if (!result || !result.landmarks || result.landmarks.length === 0) {
    return [];
  }

  return result.landmarks.map((handLandmarks, handIndex) => {
    // MediaPipe reports handedness from the *camera's* point of view. The
    // preview is mirrored, so what the user sees as their right hand is
    // labelled "Left". We keep MediaPipe's label rather than flipping it,
    // because that is the label the training data was extracted with — and
    // consistency with training matters far more here than intuition.
    const category = result.handedness?.[handIndex]?.[0];

    return {
      handedness: category?.categoryName ?? 'Right',
      landmarks: handLandmarks.map((point) => [point.x, point.y, point.z ?? 0]),
    };
  });
}
