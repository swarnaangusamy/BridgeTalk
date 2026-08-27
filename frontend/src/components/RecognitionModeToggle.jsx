/**
 * Switches between ASL fingerspelling, ISL fingerspelling and word signs.
 *
 * WHY ASL AND ISL ARE SEPARATE MODES, NOT A LANGUAGE DROPDOWN
 * -----------------------------------------------------------
 * They route to different models with different input widths. ASL fingerspells
 * with ONE hand (63 features); ISL fingerspells with TWO (126). The browser has
 * to track a different number of hands for each, so this is a real mode change
 * rather than a label swap — and presenting it as a cosmetic setting would
 * invite the assumption that one model handles both. Neither can.
 *
 * WHY THE ACCURACY NUMBERS ARE ON THE BUTTONS
 * -------------------------------------------
 * The models are not equally good, and the gaps are large. Showing them as
 * interchangeable tabs would imply a parity that does not exist, and the person
 * relying on the output is the one who would pay for that impression.
 *
 * A mode whose model is not loaded is DISABLED with the server's reason shown,
 * never hidden. A missing feature that explains itself is far easier to work
 * with than one that silently is not there.
 */

const MODES = [
  { id: 'dynamic', label: 'Words', hint: 'Word signs' },
  { id: 'isl', label: 'ISL letters', hint: 'Fingerspelling · two hands' },
  { id: 'static', label: 'ASL letters', hint: 'Fingerspelling · one hand' },
];

/**
 * The word-sign model can be trained on Indian or American data, so its label
 * comes from the model's own metadata rather than a constant here. A toggle
 * that said "ASL" while an ISL model was loaded would be worse than no label.
 */
function hintFor(option, info) {
  if (option.id !== 'dynamic') return option.hint;
  const language = info?.language;
  return language && language !== 'unknown'
    ? `${language} word signs`
    : option.hint;
}

function summarise(info) {
  if (!info) return 'not available';
  if (!info.loaded) return 'no model loaded';
  if (info.val_accuracy == null) return `${info.classes} classes`;
  return `${info.classes} classes · ${(info.val_accuracy * 100).toFixed(1)}% validation`;
}

export default function RecognitionModeToggle({
  mode,
  onChange,
  staticModelInfo,
  islModelInfo,
  dynamicModelInfo,
}) {
  const infoFor = {
    static: staticModelInfo,
    isl: islModelInfo,
    dynamic: dynamicModelInfo,
  };

  const active = infoFor[mode];
  const activeAvailable = Boolean(active?.loaded);

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
          const info = infoFor[option.id];
          const disabled = !info?.loaded;
          const selected = mode === option.id;

          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              title={disabled ? info?.error ?? 'No model loaded' : undefined}
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
              <span className="block text-xs text-slate-400">
                {hintFor(option, info)}
              </span>
            </button>
          );
        })}
      </div>

      {/* Provenance for whichever model is active, so the letter on screen is
          never separated from how reliable it is. */}
      <p className="text-xs text-slate-400">
        {MODES.find((option) => option.id === mode)?.label}
        {' · '}
        {summarise(active)}
        {mode === 'dynamic' && active?.signer_disjoint && ' · tested on unseen signers'}
      </p>

      {!activeAvailable && (
        <p
          className="rounded-lg border border-signal-warn/40 bg-signal-warn/10 p-2 text-xs text-slate-300"
          role="status"
        >
          <strong className="text-slate-100">This mode is unavailable.</strong>{' '}
          {active?.error ?? 'No model is loaded on this server.'}
        </p>
      )}
    </section>
  );
}
