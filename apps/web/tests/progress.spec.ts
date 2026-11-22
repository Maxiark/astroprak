import { test, expect, type Page } from '@playwright/test';

const tasks = [
  { id: 'a', title: 'Радиальное распределение звёзд', kind: 'generated', tags: { class: [9] } },
  { id: 'b', title: 'Кривая блеска цефеиды', kind: 'archive', tags: { class: [10] } },
  { id: 'c', title: 'Расстояние до звёзд', tags: { class: [11] } },
  { id: 'theory', title: 'Справочные материалы', kind: 'theory' },
];
function snapshot(user = 1, score = 8) {
  return { user_id: user, summary: { solved_tasks: 1, available_tasks: 3, total_score: score },
    tasks: { a: { status: 'solved', best_score: score }, b: { status: 'submitted_ungraded', best_score: null } } };
}
async function setup(page: Page) {
  const state = { user: 1, score: 8, fail: false, wrongUser: false, requests: 0, submitted: false };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/me') return route.fulfill({ json: { user_id: state.user, recovery_code: String(state.user).repeat(32) } });
    if (path === '/api/restore') {
      state.user = Number(route.request().postDataJSON().key[0]);
      return route.fulfill({ json: { status: 'ok' } });
    }
    if (path === '/api/me/progress') {
      state.requests++;
      const data = snapshot(state.wrongUser ? 99 : state.user, state.score);
      if (state.submitted) {
        data.summary.solved_tasks = 2;
        data.summary.total_score += 4.5;
        Object.assign(data.tasks, { c: { status: 'solved', best_score: 4.5 } });
      }
      return route.fulfill(state.fail ? { status: 503 } : { json: data });
    }
    if (path === '/api/tasks') return route.fulfill({ json: { tasks } });
    if (path === '/api/categories') return route.fulfill({ json: { categories: [] } });
    if (path === '/api/attempts') return route.fulfill({ json: { attempt_id: '1', task: tasks[2], submitted: false } });
    if (path.endsWith('/submit')) {
      state.submitted = true;
      return route.fulfill({ json: { submitted: true, score: 4.5, max_score: 10, grading: {} } });
    }
    return route.fulfill({ json: {} });
  });
  await page.route('**/static/**', route => route.fulfill({ contentType: 'text/html', body: '<html><body>Тестовый виджет</body></html>' }));
  return state;
}
const summary = (page: Page) => page.getByRole('region', { name: 'Ваш прогресс' });
async function restore(page: Page, user: number) {
  await page.getByRole('button', { name: /Ключ:/ }).click();
  await page.getByLabel('Ключ восстановления сессии').fill(String(user).repeat(32));
  await page.getByRole('button', { name: 'Восстановить сессию' }).click();
}

test('summary, badges, search, filter, collapse, themes and mobile', async ({ page }, testInfo) => {
  await setup(page);
  await page.goto('/');
  await expect(summary(page)).toContainText('1 из 3 задач');
  await expect(page.getByText('Решено · лучший результат: 8 баллов')).toBeVisible();
  await expect(page.getByText('Сдано — оценка недоступна')).toBeVisible();
  await expect(page.locator('.progress-badge')).toHaveCount(2);
  await page.getByLabel('Поиск заданий').fill('Расстояние');
  await expect(page.locator('.catalogue-grid h3')).toHaveCount(1);
  await expect(summary(page)).toContainText('1 из 3 задач');
  await page.getByLabel('Поиск заданий').fill('');
  await page.getByRole('button', { name: '9 кл.' }).click();
  await expect(page.locator('.catalogue-grid h3')).toHaveCount(1);
  await expect(summary(page)).toContainText('Всего баллов: 8');
  await page.getByRole('button', { name: 'Все', exact: true }).click();
  await page.locator('summary').first().click();
  await expect(summary(page)).toContainText('1 из 3 задач');
  await page.locator('summary').first().click();
  for (const theme of ['light', 'dark']) {
    await page.getByLabel('Тема', { exact: true }).selectOption(theme);
    const button = page.getByRole('button', { name: 'Решать →' }).first();
    await button.focus();
    await expect(button).toHaveCSS('outline-width', '3px');
    await button.hover();
    await expect(button).toHaveCSS('filter', 'brightness(0.92)');
    await button.evaluate(element => element.blur());
    await page.mouse.move(0, 0);
    for (const width of [1280, 375]) {
      await page.setViewportSize({ width, height: 950 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`catalogue-${theme}-${width}.png`), fullPage: true });
    }
  }
});

test('loading, error, retry and user mismatch never show fake zero', async ({ page }) => {
  const state = await setup(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/me/progress', async route => { await gate; await route.fallback(); });
  await page.goto('/');
  await expect(summary(page)).toContainText('Загрузка прогресса');
  await expect(summary(page)).not.toContainText('0 из');
  state.fail = true;
  release();
  await expect(summary(page)).toContainText('Не удалось загрузить прогресс');
  await expect(page.locator('.catalogue-grid h3')).toHaveCount(4);
  state.fail = false;
  state.wrongUser = true;
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect.poll(() => state.requests).toBe(2);
  await expect(summary(page)).toContainText('Не удалось загрузить прогресс');
  state.wrongUser = false;
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(summary(page)).toContainText('Всего баллов: 8');
});

test('A → B → A ignores delayed old response and refreshes on focus', async ({ page }) => {
  // Deliberately ignore AbortSignal: cancellation alone must not protect identity.
  await page.addInitScript(() => {
    const originalFetch = window.fetch;
    window.fetch = (input, init) => originalFetch(input,
      String(input).endsWith('/api/me/progress') ? { ...init, signal: undefined } : init);
  });
  const state = await setup(page);
  await page.goto('/');
  await expect(summary(page)).toContainText('Всего баллов: 8');
  let release!: () => void;
  let reached!: () => void;
  const waiting = new Promise<void>(resolve => { reached = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/me/progress', async route => {
    await page.unroute('**/api/me/progress');
    reached();
    await gate;
    await route.fulfill({ json: snapshot(1, 999) }).catch(() => {});
  });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await waiting;
  await expect(page.locator('.progress-badge')).toHaveCount(0);
  state.score = 4.5;
  await restore(page, 2);
  await expect(summary(page)).toContainText('Всего баллов: 4,5');
  state.score = 8;
  await restore(page, 1);
  await expect(summary(page)).toContainText('Всего баллов: 8');
  release();
  await page.waitForResponse(response => response.url().endsWith('/api/me/progress') && response.status() === 200);
  await expect(summary(page)).not.toContainText('999');
  state.score = 9;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(summary(page)).toContainText('Всего баллов: 9');
  // A different tab changes the cookie while this tab is away.
  state.user = 2;
  state.score = 2;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(summary(page)).toContainText('Всего баллов: 2');
});

test('return from submitted task refreshes progress', async ({ page }) => {
  await setup(page);
  await page.goto('/');
  await expect(summary(page)).toContainText('Всего баллов: 8');
  await page.getByRole('button', { name: 'Решать →' }).nth(2).click();
  await expect(page.locator('iframe')).toBeVisible();
  await page.frames()[1].evaluate(() => window.parent.postMessage({ type: 'ASTROSITE_SUBMIT_ATTEMPT' }, location.origin));
  await expect(page.getByText(/Сдано/).first()).toBeVisible();
  await page.getByRole('button', { name: '← Вернуться в каталог' }).click();
  await expect(summary(page)).toContainText('Всего баллов: 12,5');
  await expect(summary(page)).toContainText('2 из 3 задач');
  await expect(page.getByText('Решено · лучший результат: 4,5 баллов')).toBeVisible();
});

test('new user, zero score and empty catalogue', async ({ page }) => {
  await setup(page);
  let payload: any = { user_id: 1, summary: { solved_tasks: 0, available_tasks: 3, total_score: 0 }, tasks: {} };
  await page.route('**/api/me/progress', route => route.fulfill({ json: payload }));
  await page.goto('/');
  await expect(summary(page)).toContainText('0 из 3 задач');
  await expect(summary(page)).toContainText('Всего баллов: 0');
  payload = snapshot(1, 0);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByText('Решено · лучший результат: 0 баллов')).toBeVisible();
  payload = { user_id: 1, summary: { solved_tasks: 0, available_tasks: 0, total_score: 0 }, tasks: {} };
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(summary(page)).toContainText('Пока нет доступных задач');
  await expect(summary(page)).not.toContainText('из 0');
});
