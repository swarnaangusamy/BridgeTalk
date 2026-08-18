/**
 * Switches between fingerspelling (Model A) and word signs (Model B).
 *
 * WHY THIS COMPONENT STATES THE ACCURACY DIFFERENCE
 * -------------------------------------------------
 * The two models are not equally good, and the gap is large. Model A reaches
 * 90.5% on held-out data; Model B is trained on roughly twenty clips per word
 * and evaluated against signers it has never seen, which is a far harder test
 * and produces a far lower number.
 *
 * Presenting them as two interchangeable tabs would imply a parity that does
 * not exist, and the person relying on the output is the one who would pay for
 * that impression. So the toggle carries the numbers, and word mode is labelled
 * experimental wherever it appears.
 *
 * When the backend has no dynamic model — the normal configuration, since
 * Model B is a stretch goal — the option is disabled rather than hidden, with
 * the reason shown. A missing feature that explains itself is much easier to
 * work with than one that silently is not there.
 */

const MODES = [
  {
    id: 'static',
    label: 'Letters',
    hint: 'Fingerspelling, A–Z',
  },
  {
    id: 'dynamic',
    label: 'Words',
    hint: 'Word signs (experimental)',
  },
];

function accuracyText(info) {
  if (!info?.loaded) return null;
  if (info.val_accuracy == null) return `${info.classes} classes`;
  return `${info.classes} classes · ${(info.val_accuracy * 100).toFixed(1)}% validation`;
}

export default function RecognitionModeToggle({
  mode,
  onChange,
  staticModelInfo,
  dynamicModelInfo,
}) {
  const dynamicAvailable = Boolean(dynamicModelInfo?.loaded);

  return (
    <section aria-labelledby="recognition-mode-heading" className="flex flex-col gap-2">
      <h3
        id="recognition-mode-heading"
        className="text-sm font-semibold uppercase tracking-wide text-slate-400"
      >
        Recognition mode
      </h3>

      <div role="radiogroup" aria-labelledby="recognition-mode-heading" className="flex gap-2">
        {MODES.map((option) => {
          const isDynamic = option.id === 'dynamic';
          const disabled = isDynamic && !dynamicAvailable;
          const selected = mode === option.id;

          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(option.id)}
              className={[
                'flex-1 rounded-lg border px-3 py-2 text-left transition-colors',
                selected
                  ? 'border-bridge-500 bg-bridge-500/15 text-slate-100'
                  : 'border-ink-700 bg-ink-800 text-slate-300 hover:bg-ink-700',
                disabled ? 'cursor-not-allowed opacity-40 hover:bg-ink-800' : '',
              ].join(' ')}
            >
              <span className="block text-sm font-semibold">{option.label}</span>
              <span className="block text-xs text-slate-400">{option.hint}</span>
            </button>
          );
        })}
      </div>

      {/* Provenance for whichever model is active, so the number on screen is
          never separated from how reliable it is. */}
      <p className="text-xs text-slate-400">
        {mode === 'dynamic' ? (
          dynamicAvailable ? (
            <>
              Word signs · {accuracyText(dynamicModelInfo)}
              {dynamicModelInfo?.signer_disjoint && (
                <> · tested on unseen signers</>
              )}
            </>
          ) : (
            <>Word-sign model unavailable.</>
          )
        ) : (
          <>Fingerspelling · {accuracyText(staticModelInfo) ?? 'no model loaded'}</>
        )}
      </p>

      {!dynamicAvailable && (
        <p className="rounded-lg border border-ink-700 bg-ink-900 p-2 text-xs text-slate-400">
          <strong className="text-slate-300">Word signs unavailable.</strong>{' '}
          {dynamicModelInfo?.error ??
            'No dynamic model is loaded on this server.'}{' '}
          Fingerspelling is unaffected.
        </p>
      )}
    </section>
  );
}
