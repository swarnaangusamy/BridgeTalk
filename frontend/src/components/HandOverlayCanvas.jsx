import { useEffect, useRef } from 'react';

/**
 * Draws the 21-point hand skeleton over the video.
 *
 * This is decoration in the sense that recognition works without it, and
 * essential in every other sense: it is the single most convincing element of
 * the demo. A skeleton tracking your fingers makes it immediately obvious that
 * the system is reading hand *geometry* rather than guessing from pixels, and
 * it turns "no hand detected" from a mystery into something you can see and fix
 * by moving your hand.
 *
 * The canvas is a sibling of the <video>, absolutely positioned on top, and
 * sized in device pixels so lines stay crisp on a Retina display.
 */

// MediaPipe's landmark indices, connected into a hand.
const HAND_CONNECTIONS = [
  [0, 1], [1, 2], [2, 3], [3, 4],            // thumb
  [0, 5], [5, 6], [6, 7], [7, 8],            // index
  [5, 9], [9, 10], [10, 11], [11, 12],       // middle
  [9, 13], [13, 14], [14, 15], [15, 16],     // ring
  [13, 17], [17, 18], [18, 19], [19, 20],    // little
  [0, 17],                                    // palm edge
];

export default function HandOverlayCanvas({ landmarks, mirrored = true, stable = false }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d');
    const { width, height } = canvas;

    context.clearRect(0, 0, width, height);
    if (!landmarks || landmarks.length === 0) return;

    // Green once the prediction is stable, blue while still settling. The
    // colour change is peripheral feedback: you can tell recognition has
    // locked on without looking away from your own hand.
    const strokeColour = stable ? 'rgba(74, 222, 128, 0.95)' : 'rgba(56, 189, 248, 0.95)';

    for (const hand of landmarks) {
      // MediaPipe returns normalised [0,1] coordinates. The preview is
      // mirrored so signing feels natural, so x must be flipped to match.
      const points = hand.map((point) => ({
        x: (mirrored ? 1 - point.x : point.x) * width,
        y: point.y * height,
      }));

      context.lineWidth = Math.max(2, width / 320);
      context.strokeStyle = strokeColour;
      context.lineCap = 'round';

      context.beginPath();
      for (const [start, end] of HAND_CONNECTIONS) {
        context.moveTo(points[start].x, points[start].y);
        context.lineTo(points[end].x, points[end].y);
      }
      context.stroke();

      points.forEach((point, index) => {
        // The wrist is drawn larger: it is the normalisation origin, the one
        // landmark whose position defines every other value sent to the model.
        const radius = index === 0 ? Math.max(6, width / 110) : Math.max(3, width / 200);

        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fillStyle = index === 0 ? strokeColour : 'rgba(255, 255, 255, 0.95)';
        context.fill();
        context.lineWidth = 1;
        context.strokeStyle = 'rgba(15, 23, 42, 0.8)';
        context.stroke();
      });
    }
  }, [landmarks, mirrored, stable]);

  return (
    <canvas
      ref={canvasRef}
      width={640}
      height={480}
      className="pointer-events-none absolute inset-0 h-full w-full"
      // Purely decorative: the same information is announced as text in
      // SignDetectionPanel, so a screen reader should skip it rather than
      // read out a meaningless canvas element.
      aria-hidden="true"
    />
  );
}
