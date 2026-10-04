import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import History from '../pages/History';
import Home from '../pages/Home';
import Lobby from '../pages/Lobby';
import Login from '../pages/Login';
import MeetingEnded from '../pages/MeetingEnded';
import MeetingRoom from '../pages/MeetingRoom';
import SignDetection from '../pages/SignDetection';
import Transcript from '../pages/Transcript';
import { installApiStub, renderPage } from './renderPage';

/**
 * Every page renders without throwing.
 *
 * THIS SUITE EXISTS BECAUSE OF A SPECIFIC FAILURE
 * -----------------------------------------------
 * MeetingRoom shipped with eleven use-before-define errors. Each one threw
 * "Cannot access 'X' before initialization" the moment the component rendered,
 * and the meeting screen showed the error boundary instead of the meeting.
 * `vite build` passed, because bundling does not evaluate the module.
 *
 * So the assertion each test makes is the one that was missing: mount the page,
 * and fail if anything throws. The afterEach hook in setup.js additionally fails
 * the test if React logged a render error into console.error, which is how a
 * crash caught by an error boundary would otherwise go unnoticed.
 */
describe('every page renders', () => {
  beforeEach(() => {
    installApiStub();
  });

  it('Login', async () => {
    renderPage(<Login initialMode="login" />, { path: '/login' });
    expect(await screen.findByText('Sign in to BridgeTalk')).toBeTruthy();
  });

  it('Register', async () => {
    renderPage(<Login initialMode="register" />, { path: '/register' });
    expect(await screen.findByText('Create your account')).toBeTruthy();
    // The two register-only fields the specification asks for.
    expect(screen.getByLabelText(/Full name/i)).toBeTruthy();
    expect(screen.getByLabelText(/Confirm password/i)).toBeTruthy();
  });

  it('Home', async () => {
    renderPage(<Home />, { path: '/' });
    expect(await screen.findByRole('button', { name: /New meeting/i })).toBeTruthy();
    // Recent meetings arrive from the stubbed history endpoint.
    expect(await screen.findByText('Project review')).toBeTruthy();
  });

  it('History', async () => {
    renderPage(<History />, { path: '/history' });
    expect(await screen.findByText('Meeting history')).toBeTruthy();
    expect(await screen.findByText('Project review')).toBeTruthy();
  });

  it('Transcript', async () => {
    renderPage(<Transcript />, { path: '/history/:code', entry: '/history/K7Q-2M4' });
    expect(await screen.findByText('good morning')).toBeTruthy();
    expect(await screen.findByRole('button', { name: /Download TXT/i })).toBeTruthy();
    expect(await screen.findByRole('button', { name: /Download PDF/i })).toBeTruthy();
  });

  it('Lobby', async () => {
    renderPage(<Lobby />, { path: '/lobby/:code', entry: '/lobby/K7Q-2M4' });
    expect(await screen.findByText('Ready to join?')).toBeTruthy();
    expect(
      await screen.findByText(/I will be signing in this meeting/i),
    ).toBeTruthy();
  });

  it('MeetingRoom', async () => {
    renderPage(<MeetingRoom />, { path: '/meeting/:code', entry: '/meeting/K7Q-2M4' });

    // The control bar is the proof the page got all the way through render.
    expect(await screen.findByRole('button', { name: /Turn off microphone/i })).toBeTruthy();
    expect(await screen.findByRole('button', { name: /Turn off camera/i })).toBeTruthy();
    expect(await screen.findByRole('button', { name: /Hide captions/i })).toBeTruthy();
    expect(await screen.findByRole('button', { name: /Leave call/i })).toBeTruthy();
  });

  it('MeetingEnded', async () => {
    renderPage(<MeetingEnded />, { path: '/ended/:code', entry: '/ended/K7Q-2M4' });
    expect(await screen.findByText('You left the meeting')).toBeTruthy();
    expect(
      await screen.findByText(/The transcript of this meeting has been saved/i),
    ).toBeTruthy();
  });

  it('SignDetection', async () => {
    renderPage(<SignDetection />, { path: '/detect' });
    expect(await screen.findByText('Sign recognition check')).toBeTruthy();
  });
});

describe('the meeting room honours the lobby', () => {
  beforeEach(() => {
    installApiStub();
  });

  /**
   * Device choices are read from sessionStorage, not the URL.
   *
   * Reported problem 6 was a raw deviceId in the join link. The lobby was moved
   * to sessionStorage, but the meeting room was still reading
   * `searchParams.get('camera')` — which is now always null, so every meeting
   * silently used the system default camera and the lobby's picker did nothing.
   */
  it('requests the camera and microphone chosen in the lobby', async () => {
    sessionStorage.setItem(
      'bridgetalk.devices',
      JSON.stringify({ micId: 'mic-1', cameraId: 'cam-1', willSign: true }),
    );

    renderPage(<MeetingRoom />, { path: '/meeting/:code', entry: '/meeting/K7Q-2M4' });
    await screen.findByRole('button', { name: /Leave call/i });

    await waitFor(() => {
      expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled();
    });

    const constraints = navigator.mediaDevices.getUserMedia.mock.calls[0][0];
    expect(constraints.video.deviceId).toEqual({ exact: 'cam-1' });
    expect(constraints.audio.deviceId).toEqual({ exact: 'mic-1' });
    // Echo cancellation is not optional: speech recognition runs on this
    // microphone, so the remote voice coming back would be transcribed as if
    // this user had said it.
    expect(constraints.audio.echoCancellation).toBe(true);
    expect(constraints.audio.noiseSuppression).toBe(true);
  });

  /**
   * Sign recognition is opt-in, and the lobby checkbox is what opts in.
   *
   * It defaulted to true for everyone, which is why a hearing participant's
   * resting hands were being recognised as signs ("M at 71%").
   */
  it('starts with sign recognition off unless the lobby asked for it', async () => {
    renderPage(<MeetingRoom />, { path: '/meeting/:code', entry: '/meeting/K7Q-2M4' });
    expect(
      await screen.findByRole('button', { name: /Turn on sign recognition/i }),
    ).toBeTruthy();
  });

  it('starts with sign recognition on when the lobby asked for it', async () => {
    sessionStorage.setItem('bridgetalk.devices', JSON.stringify({ willSign: true }));

    renderPage(<MeetingRoom />, { path: '/meeting/:code', entry: '/meeting/K7Q-2M4' });
    expect(
      await screen.findByRole('button', { name: /Turn off sign recognition/i }),
    ).toBeTruthy();
  });

  /** Captions are on by default for everyone, per the specification. */
  it('shows captions by default', async () => {
    renderPage(<MeetingRoom />, { path: '/meeting/:code', entry: '/meeting/K7Q-2M4' });
    expect(await screen.findByRole('button', { name: /Hide captions/i })).toBeTruthy();
    expect(await screen.findByLabelText('Live captions')).toBeTruthy();
  });
});
