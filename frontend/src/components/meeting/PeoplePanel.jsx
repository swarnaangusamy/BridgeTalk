import Avatar from '../ui/Avatar';
import Icon from '../ui/Icon';

/**
 * Who is in the call, with their microphone and camera state.
 *
 * WHAT THIS CAN AND CANNOT KNOW
 * -----------------------------
 * The local user's state is read directly. The remote user's is INFERRED from
 * their media tracks: a track that is absent or has `muted = true` means no
 * media is arriving. That is a genuine signal, but it is not the same as "they
 * pressed the mute button" — a dropped network also stops the track.
 *
 * So the states are labelled honestly ("No audio arriving" rather than "Muted")
 * for the remote participant. Claiming to know the other person pressed a
 * button, and being wrong, is worse than describing what is actually observable.
 */
export default function PeoplePanel({
  localName,
  localMuted,
  localCameraOff,
  localSigning,
  remoteName,
  remoteStream,
  remoteSigning,
  connectionState,
}) {
  const remoteAudio = remoteStream?.getAudioTracks?.()[0];
  const remoteVideo = remoteStream?.getVideoTracks?.()[0];

  const remoteHasAudio = Boolean(remoteAudio && !remoteAudio.muted);
  const remoteHasVideo = Boolean(remoteVideo && !remoteVideo.muted);

  return (
    <ul className="flex flex-col gap-1 pt-1">
      <Person
        name={localName}
        suffix="(you)"
        signing={localSigning}
        states={[
          localMuted
            ? { icon: 'mic_off', text: 'Microphone off', danger: true }
            : { icon: 'mic', text: 'Microphone on' },
          localCameraOff
            ? { icon: 'videocam_off', text: 'Camera off', danger: true }
            : { icon: 'videocam', text: 'Camera on' },
        ]}
      />

      {remoteName ? (
        <Person
          name={remoteName}
          signing={remoteSigning}
          states={[
            remoteHasAudio
              ? { icon: 'mic', text: 'Audio arriving' }
              : { icon: 'mic_off', text: 'No audio arriving', danger: true },
            remoteHasVideo
              ? { icon: 'videocam', text: 'Video arriving' }
              : { icon: 'videocam_off', text: 'No video arriving', danger: true },
          ]}
        />
      ) : (
        <li className="px-1 py-6 text-center text-sm text-dark-muted">
          Nobody else has joined yet.
          {connectionState && connectionState !== 'new'
            ? ` Connection is ${connectionState}.`
            : ''}
        </li>
      )}
    </ul>
  );
}

function Person({ name, suffix, signing, states }) {
  return (
    <li className="flex items-start gap-3 rounded-card px-1 py-2.5">
      <Avatar name={name} size={36} />
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-sm text-dark-text">
          <span className="min-w-0 truncate">{name}</span>
          {suffix ? <span className="shrink-0 text-dark-muted">{suffix}</span> : null}
          {signing ? (
            <Icon name="sign_language" size={15} className="shrink-0 text-dark-accent" />
          ) : null}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {states.map((state) => (
            <span
              key={state.text}
              className={`inline-flex items-center gap-1 text-xs
                          ${state.danger ? 'text-dark-danger' : 'text-dark-muted'}`}
            >
              <Icon name={state.icon} size={14} />
              {state.text}
            </span>
          ))}
        </p>
      </div>
    </li>
  );
}
