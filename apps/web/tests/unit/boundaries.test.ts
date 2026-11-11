import { ESLint } from 'eslint';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(__dirname, '../..');

async function lint(filePath: string, code: string) {
  const eslint = new ESLint({ cwd: root });
  const [result] = await eslint.lintText(code, { filePath: path.join(root, filePath) });
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports');
}

describe('import boundaries', () => {
  it('rejects a presentation component importing the API client', async () => {
    const msgs = await lint('src/components/shell/Bad.tsx', "import { get } from '@/api/client';\nexport const x = get;\n");
    expect(msgs).toHaveLength(1);
  });

  it('rejects components importing state and api queries', async () => {
    expect(await lint('src/components/Bad.tsx', "import { s } from '@/state/ui-store';\nexport const x = s;\n")).toHaveLength(1);
    expect(await lint('src/components/Bad.tsx', "import { q } from '@/api/queries';\nexport const x = q;\n")).toHaveLength(1);
  });

  it('allows components to import types from api/schema, design-system and lib', async () => {
    const code =
      "import type { paths } from '@/api/schema';\nimport { EnvironmentPill } from '@/design-system/primitives/EnvironmentPill';\nexport type T = paths;\nexport const x = EnvironmentPill;\n";
    expect(await lint('src/components/shell/Ok.tsx', code)).toHaveLength(0);
  });

  it('rejects design-system importing anything internal', async () => {
    expect(await lint('src/design-system/primitives/Bad.tsx', "import { x } from '@/lib/format';\nexport const y = x;\n")).not.toHaveLength(0);
  });

  it('rejects anything importing the prototype', async () => {
    expect(await lint('src/features/Bad.tsx', "import x from '../../prototype/support.js';\nexport default x;\n")).toHaveLength(1);
  });

  it('allows features to import api', async () => {
    expect(await lint('src/features/Ok.tsx', "import { get } from '@/api/client';\nexport const x = get;\n")).toHaveLength(0);
  });

  it('rejects components importing the whole API layer, not only listed modules', async () => {
    expect(await lint('src/components/A.tsx', "import { a } from '@/api';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/components/A.tsx', "import { a } from '@/api/x';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/components/A.tsx', "import { a } from '@/api/hooks';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/components/shell/A.tsx', "import { a } from '../../api/client';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/components/shell/A.tsx', "import { a } from '../../api';\nexport const x = a;\n")).toHaveLength(1);
  });

  it('allows a type import from api/schema in a component', async () => {
    expect(await lint('src/components/A.tsx', "import type { paths } from '@/api/schema';\nexport type T = paths;\n")).toHaveLength(0);
  });

  it('rejects app reaching into the API layer', async () => {
    expect(await lint('src/app/x/page.tsx', "import { a } from '@/api';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/app/x/page.tsx', "import { a } from '@/api/hooks';\nexport const x = a;\n")).toHaveLength(1);
  });

  it('rejects api importing design-system, lib or state', async () => {
    expect(await lint('src/api/client.ts', "import { a } from '@/design-system/primitives/X';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/api/client.ts', "import { a } from '@/lib/format';\nexport const x = a;\n")).toHaveLength(1);
    expect(await lint('src/api/client.ts', "import { a } from '@/state/ui-store';\nexport const x = a;\n")).toHaveLength(1);
  });

  it('rejects lib importing api, components, features, state or app', async () => {
    for (const mod of ['@/api/client', '@/components/X', '@/features/X', '@/state/ui-store', '@/app/x']) {
      expect(await lint('src/lib/format.ts', `import { a } from '${mod}';\nexport const x = a;\n`)).toHaveLength(1);
    }
  });

  it('rejects state importing components, features or app', async () => {
    for (const mod of ['@/components/X', '@/features/X', '@/app/x']) {
      expect(await lint('src/state/ui-store.ts', `import { a } from '${mod}';\nexport const x = a;\n`)).toHaveLength(1);
    }
  });
});
