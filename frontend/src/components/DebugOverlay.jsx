/**
 * Diagnostics, shown only with ?debug=1 in the URL.
 *
 * Exists because "I spoke and nothing happened" is not a reportable bug — it
 * could be the microphone track, the recogniser, the socket, the server, or
 * the render. This shows each stage so a tester can say which one is dead.
 */
export default function DebugOverlay({
  micTrack,
  cameraTrack,
  speech,
  sign,
  socketStatus,
  lastSent,
  lastReceived,
}) {
  const Row = ({ label, value, warn = false }) => (
    <div className="flex justify-between gap-3">
      <span className="text-[#9AA0A6]">{label}</span>
      <span className={warn ? 'text-[#EA4335]' : 'text-[#E8EAED]'}>{String(value ?? '—')}</span>
    </div>
  );

  return (
    <aside
      className="fixed bottom-2 left-2 z-50 w-[340px] space-y-1 rounded-lg border border-[#5F6368] bg-black/90 p-3 font-mono text-[11px]"
      aria-label="Debug diagnostics"
    >
      <p className="mb-1 font-semibold text-[#8AB4F8]">BridgeTalk diagnostics</p>

      <Row label="mic track" value={micTrack} warn={micTrack !== 'live'} />
      <Row label="camera track" value={cameraTrack} />
      <Row label="ws" value={socketStatus} warn={socketStatus !== 'open'} />

      <p className="mt-2 font-semibold text-[#8AB4F8]">speech</p>
      <Row label="engine" value={speech?.engineActive} />
      <Row label="state" value={speech?.state} warn={speech?.state === 'error'} />
      <Row label="interim" value={speech?.lastInterim || '(none)'} />
      <Row label="error" value={speech?.error || 'none'} warn={Boolean(speech?.error)} />

      <p className="mt-2 font-semibold text-[#8AB4F8]">sign</p>
      <Row label="phase" value={sign?.phase} />
      <Row label="motion" value={sign?.motion} />
      <Row label="committed" value={sign?.committed} />
      <Row label="rejected" value={sign?.rejected} />
      <Row label="segment" value={sign?.openSegment || '(none)'} />

      <p className="mt-2 font-semibold text-[#8AB4F8]">captions</p>
      <Row label="last sent" value={lastSent} />
      <Row label="last recv" value={lastReceived} />
    </aside>
  );
}
