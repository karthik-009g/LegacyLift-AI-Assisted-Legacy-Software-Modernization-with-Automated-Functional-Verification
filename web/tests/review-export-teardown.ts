import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

export default async function teardown() {
  const fixtureHome = process.env.LEGACYLIFT_REVIEW_E2E_HOME;
  if (!fixtureHome) return;

  const resolvedHome = path.resolve(fixtureHome);
  const isExpectedTemporaryPath =
    path.dirname(resolvedHome) === path.resolve(tmpdir())
    && path.basename(resolvedHome).startsWith('legacylift-review-e2e-');
  if (!isExpectedTemporaryPath || !existsSync(resolvedHome)) {
    throw new Error('Refusing to clean an unexpected synthetic E2E fixture path.');
  }

  const marker = path.join(resolvedHome, '.legacylift-e2e-fixture');
  const isOwnedFixture = existsSync(marker)
    && readFileSync(marker, 'utf8') === 'LegacyLift disposable synthetic UI test fixture\n';
  const isEmptyTemporaryDirectory = readdirSync(resolvedHome).length === 0;
  if (!isOwnedFixture && !isEmptyTemporaryDirectory) {
    throw new Error('Refusing to clean a temporary directory without the E2E ownership marker.');
  }

  rmSync(resolvedHome, { recursive: true, force: true });
}
