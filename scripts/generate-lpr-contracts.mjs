import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..');
const specPath = path.join(repoRoot, 'schemas', 'lpr', 'lpr-contracts.json');
const tsOutPath = path.join(repoRoot, 'src', 'shared', 'contracts', 'lpr.generated.ts');
const rustOutPath = path.join(repoRoot, 'src-tauri', 'src', 'contracts', 'lpr_generated.rs');
const checkMode = process.argv.includes('--check');

const primitiveTs = {
  string: 'string',
  number: 'number',
  boolean: 'boolean',
  json: 'Record<string, unknown>',
};

const primitiveRust = {
  string: 'String',
  number: 'f64',
  boolean: 'bool',
  json: 'Value',
};

const definitionTargets = (definition) => new Set(definition.targets ?? ['ts', 'rust', 'python']);

const toSnakeCase = (value) => value.replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/-/g, '_').toLowerCase();

const isPrimitive = (value) => ['string', 'number', 'boolean', 'json'].includes(value);

function buildDefinitionMap(spec) {
  const map = new Map();
  for (const [name, external] of Object.entries(spec.externals ?? {})) {
    map.set(name, { ...external, name, external: true });
  }
  for (const definition of spec.definitions) {
    map.set(definition.name, definition);
  }
  return map;
}

function tsTypeForNode(node, definitionMap) {
  if (node.type === 'array') {
    return `${tsTypeForNode({ type: node.items }, definitionMap)}[]`;
  }
  if (isPrimitive(node.type)) {
    return primitiveTs[node.type];
  }
  const definition = definitionMap.get(node.type);
  if (!definition) {
    throw new Error(`Unknown TS type reference: ${node.type}`);
  }
  return definition.name;
}

function rustTypeName(name, definitionMap) {
  if (isPrimitive(name)) {
    return primitiveRust[name];
  }
  const definition = definitionMap.get(name);
  if (!definition) {
    throw new Error(`Unknown Rust type reference: ${name}`);
  }
  if (definition.external) {
    return definition.rustName ?? `${definition.name}Payload`;
  }
  return definition.rustName ?? definition.name;
}

function rustTypeForField(field, definitionMap) {
  let baseType;
  if (field.type === 'array') {
    baseType = `Vec<${rustTypeName(field.items, definitionMap)}>`;
  } else if (field.rustType) {
    baseType = field.rustType;
  } else {
    baseType = rustTypeName(field.type, definitionMap);
  }

  if (field.optional || field.nullable) {
    return `Option<${baseType}>`;
  }
  return baseType;
}

function renderTs(spec) {
  const definitionMap = buildDefinitionMap(spec);
  const tsDefinitions = spec.definitions.filter((definition) => definitionTargets(definition).has('ts'));
  const usedExternalImports = new Set();

  for (const definition of tsDefinitions) {
    if (definition.kind !== 'object') {
      continue;
    }
    for (const field of definition.fields ?? []) {
      collectTsExternalTypes(field, definitionMap, usedExternalImports);
    }
  }

  const imports = (spec.ts?.imports ?? [])
    .filter((entry) => usedExternalImports.has(entry.name))
    .map((entry) => `import type { ${entry.name} } from '${entry.from}';`);

  const chunks = ['// This file is auto-generated from schemas/lpr/lpr-contracts.json.', '// Do not edit manually.', ''];
  if (imports.length > 0) {
    chunks.push(...imports, '');
  }

  for (const definition of tsDefinitions) {
    if (definition.kind === 'stringUnion') {
      const values = definition.values.map((value) => `'${value}'`).join(' | ');
      chunks.push(`export type ${definition.name} = ${values};`, '');
      continue;
    }
    if (definition.kind === 'alias') {
      chunks.push(`export type ${definition.name} = ${definition.tsType};`, '');
      continue;
    }
    if (definition.kind === 'object') {
      chunks.push(`export interface ${definition.name} {`);
      for (const field of definition.fields ?? []) {
        const optionalMarker = field.optional ? '?' : '';
        const type = tsTypeForNode(field, definitionMap);
        const nullableType = field.nullable ? `${type} | null` : type;
        chunks.push(`  ${field.name}${optionalMarker}: ${nullableType};`);
      }
      chunks.push('}', '');
      continue;
    }
    throw new Error(`Unsupported TS definition kind: ${definition.kind}`);
  }

  return `${chunks.join('\n').trimEnd()}\n`;
}

function collectTsExternalTypes(field, definitionMap, usedExternalImports) {
  if (field.type === 'array') {
    collectTsExternalTypes({ type: field.items }, definitionMap, usedExternalImports);
    return;
  }
  if (isPrimitive(field.type)) {
    return;
  }
  const definition = definitionMap.get(field.type);
  if (!definition) {
    throw new Error(`Unknown TS type reference: ${field.type}`);
  }
  if (definition.external) {
    usedExternalImports.add(definition.name);
  }
}

function renderRust(spec) {
  const definitionMap = buildDefinitionMap(spec);
  const rustDefinitions = spec.definitions.filter((definition) => definitionTargets(definition).has('rust'));
  const usedExternalRefs = new Set();

  for (const definition of rustDefinitions) {
    if (definition.kind !== 'object') {
      continue;
    }
    for (const field of definition.fields ?? []) {
      collectRustExternalTypes(field, definitionMap, usedExternalRefs);
    }
  }

  const header = ['// This file is auto-generated from schemas/lpr/lpr-contracts.json.', '// Do not edit manually.', 'use serde::{Deserialize, Serialize};', 'use serde_json::Value;'];
  if (usedExternalRefs.size > 0) {
    header.push(`use super::{${[...usedExternalRefs].sort().join(', ')}};`);
  }
  header.push('');

  const chunks = [...header];
  for (const definition of rustDefinitions) {
    if (definition.kind === 'stringUnion') {
      chunks.push(`pub type ${definition.rustName ?? definition.name} = String;`, '');
      continue;
    }
    if (definition.kind === 'alias') {
      chunks.push(`pub type ${definition.rustName ?? definition.name} = ${definition.rustType};`, '');
      continue;
    }
    if (definition.kind === 'object') {
      chunks.push('#[derive(Debug, Clone, Serialize, Deserialize)]');
      chunks.push('#[serde(rename_all = "camelCase")]');
      chunks.push(`pub struct ${definition.rustName ?? definition.name} {`);
      for (const field of definition.fields ?? []) {
        const rustFieldName = toRustFieldName(field.name);
        chunks.push(`    pub ${rustFieldName}: ${rustTypeForField(field, definitionMap)},`);
      }
      chunks.push('}', '');
      continue;
    }
    throw new Error(`Unsupported Rust definition kind: ${definition.kind}`);
  }

  return `${chunks.join('\n').trimEnd()}\n`;
}

function collectRustExternalTypes(field, definitionMap, usedExternalRefs) {
  if (field.type === 'array') {
    collectRustExternalTypes({ type: field.items }, definitionMap, usedExternalRefs);
    return;
  }
  if (isPrimitive(field.type)) {
    return;
  }
  const definition = definitionMap.get(field.type);
  if (!definition) {
    throw new Error(`Unknown Rust type reference: ${field.type}`);
  }
  if (definition.external) {
    usedExternalRefs.add(definition.rustName ?? `${definition.name}Payload`);
  }
}

function toRustFieldName(name) {
  const snakeCase = toSnakeCase(name);
  if (snakeCase === 'box') {
    return 'r#box';
  }
  return snakeCase;
}

async function main() {
  const spec = JSON.parse(await readFile(specPath, 'utf8'));
  const tsOutput = renderTs(spec);
  const rustOutput = renderRust(spec);

  if (checkMode) {
    await assertGeneratedFileUpToDate(tsOutPath, tsOutput);
    await assertGeneratedFileUpToDate(rustOutPath, rustOutput);
    return;
  }

  await mkdir(path.dirname(tsOutPath), { recursive: true });
  await mkdir(path.dirname(rustOutPath), { recursive: true });
  await writeFile(tsOutPath, tsOutput, 'utf8');
  await writeFile(rustOutPath, rustOutput, 'utf8');
}

async function assertGeneratedFileUpToDate(filePath, expected) {
  let current;
  try {
    current = await readFile(filePath, 'utf8');
  } catch (error) {
    throw new Error(`Generated file is missing: ${path.relative(repoRoot, filePath)}`);
  }

  if (current !== expected) {
    throw new Error(
      `Generated file is out of date: ${path.relative(repoRoot, filePath)}. Run \"npm run generate:lpr-contracts\".`,
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
