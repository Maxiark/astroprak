import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const widget = readFileSync('../../data/tasks/radial-cluster/widget.html', 'utf8');
const answers = { current_step: 5, center_alpha: 14.75, center_delta: -72.19,
  user_counts: [1, 2, 3, 4, 5], current_m: 5, model_type: 'king', rc_val: 0.032, n0_val: 13 };
const task = { id: 'radial-cluster', title: 'Радиальное распределение', data: {} };
const uncertain = 'Не удалось получить подтверждение сдачи. Работа могла сохраниться. Повторите отправку — принятый результат не изменится.';
async function setup(page: Page, submitted = false) {
  const state = { calls: 0, creates: 0, events: 0, mode: 'ok', accepted: submitted ? { ...answers } : null as any,
    bodies: [] as any[], conflict: false };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/me') return route.fulfill({ json: { user_id: 1, recovery_code: '1'.repeat(32) } });
    if (path === '/api/tasks') return route.fulfill({ json: { tasks: [task] } });
    if (path === '/api/categories') return route.fulfill({ json: { categories: [] } });
    if (path === '/api/attempts') {
      state.creates++;
      return route.fulfill({ json: { attempt_id: '42', task, answers, submitted,
        grading: submitted ? { score: 4, max_score: 5 } : null } });
    }
    if (path.endsWith('/submit')) {
      state.calls++;
      state.bodies.push(route.request().postDataJSON().answers);
      if (state.mode === 'hang') return;
      if (state.mode === 'network') return route.abort('failed');
      state.accepted ||= route.request().postDataJSON().answers;
      if (state.mode === 'lost') return route.abort('failed');
      return route.fulfill({ json: { attempt_id: '42', answers: state.accepted, score: 4, max_score: 5,
        grading: { score: 4, max_score: 5 } } });
    }
    if (path.endsWith('/events')) { state.events++; return; }
    if (path.endsWith('/answers') && state.conflict) return route.fulfill({ status: 409,
      json: { detail: { code: 'ATTEMPT_ALREADY_SUBMITTED' } } });
    return route.fulfill({ json: {} });
  });
  await page.route('**/static/**', route => route.fulfill({ contentType: 'text/html', body: widget }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Решать →' }).click();
  await expect(page.frameLocator('iframe').locator('#btn-final-submit')).toBeVisible();
  return state;
}
const frame = (page: Page) => page.frameLocator('iframe');
const button = (page: Page) => frame(page).locator('#btn-final-submit');
async function message(page: Page, type: string, extra = {}) {
  await page.frames()[1].evaluate(data => parent.postMessage(data, location.origin), { type, ...extra });
}
async function success(page: Page) {
  await expect(button(page)).toHaveText('Работа сдана');
  await expect(frame(page).locator('#session-score-title')).toContainText('4 из 5');
  await expect(frame(page).locator('#param-rc')).toBeDisabled();
}

test('normal submission is independent of hanging analytics', async ({ page }) => {
  const state = await setup(page);
  await message(page, 'ASTROSITE_EVENT', { name: 'test' });
  await button(page).click();
  await success(page);
  expect(state.calls).toBe(1);
  expect(state.events).toBe(1);
});

test('submitted attempt returns accepted answers, including zero counts', async ({ page }) => {
  const state = await setup(page, true);
  state.accepted = { ...answers, rc_val: 0.05, user_counts: [0, 0, 0, 0, 0] };
  await message(page, 'ASTROSITE_SUBMIT_ATTEMPT', { answers: { ...answers, rc_val: 0.08 } });
  await expect.poll(() => state.calls).toBe(1);
  await success(page);
  await expect(frame(page).locator('#param-rc')).toHaveValue('0.05');
  await expect(frame(page).locator('#ring-user-0')).toHaveValue('0');
  expect(state.creates).toBe(1);
  // A late error must not unlock a confirmed submission.
  await page.evaluate(() => document.querySelector('iframe')!.contentWindow!.postMessage({
    type: 'ASTROSITE_SUBMIT_ERROR', error: 'Late error'
  }, location.origin));
  await expect(button(page)).toBeDisabled();
  await expect(frame(page).locator('#param-rc')).toBeDisabled();
});

test('back-to-back messages share one request', async ({ page }) => {
  const state = await setup(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route('**/submit', async route => { requests++; await gate; await route.fallback(); });
  await page.frames()[1].evaluate(answers => {
    document.getElementById('btn-final-submit')!.click();
    parent.postMessage({ type: 'ASTROSITE_SUBMIT_ATTEMPT', answers }, location.origin);
  }, answers);
  await expect.poll(() => requests).toBe(1);
  release();
  await success(page);
  expect(state.calls).toBe(1);
});

for (const mode of ['hang', 'network', 'lost']) {
  test(`${mode}: preserves answers and permits idempotent retry`, async ({ page }) => {
    const state = await setup(page);
    await page.clock.install();
    await page.clock.pauseAt(new Date());
    state.mode = mode;
    await frame(page).locator('#param-rc').fill('0.045');
    await button(page).click();
    await expect.poll(() => state.calls).toBe(1);
    if (mode === 'hang') {
      await page.clock.fastForward(29_999);
      await expect(button(page)).toBeDisabled();
      await page.clock.fastForward(1);
    }
    await expect(frame(page).locator('#submit-error')).toHaveText(uncertain);
    await expect(button(page)).toBeEnabled();
    await expect(frame(page).locator('#param-rc')).toHaveValue('0.045');
    const accepted = state.accepted;
    state.mode = 'ok';
    await button(page).click();
    await success(page);
    expect(state.calls).toBe(2);
    expect(state.creates).toBe(1);
    expect(state.bodies[1]).toEqual(state.bodies[0]);
    if (mode === 'lost') expect(state.accepted).toEqual(accepted);
  });
}

test('reload after interrupted submit ignores legacy local submitted flag', async ({ page }) => {
  const state = await setup(page);
  state.mode = 'hang';
  await button(page).click();
  await expect.poll(() => state.calls).toBe(1);
  await page.frames()[1].evaluate(() => {
    const key = Object.keys(localStorage).find(key => key.startsWith('astrosite_rc_'))!;
    const saved = JSON.parse(localStorage.getItem(key)!);
    if ('isSubmitted' in saved) throw new Error('Submission state must not be persisted');
    localStorage.setItem(key, JSON.stringify({ ...saved, isSubmitted: true }));
    location.reload();
  });
  await expect(button(page)).toBeEnabled();
  await expect(frame(page).locator('#session-banner')).toBeHidden();
});

test('draft conflict keeps the submission and autosave protection', async ({ page }) => {
  // Exercise conflict handling without depending on the unrelated draft debounce.
  await page.addInitScript(() => {
    const original = window.setTimeout;
    window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: any[]) => {
      if (delay === 350 && typeof handler === 'function') { queueMicrotask(() => handler(...args)); return 0; }
      return original(handler, delay, ...args);
    }) as typeof window.setTimeout;
  });
  const state = await setup(page);
  state.conflict = true;
  await message(page, 'ASTROSITE_ANSWER_CHANGE', { answers });
  await expect(page.getByRole('alert')).toContainText('Обновите страницу');
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(state.calls).toBe(0);
});
