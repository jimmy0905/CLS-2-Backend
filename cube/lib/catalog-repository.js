'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const IDENTIFIER = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/;
const SUPPORTED_FIELD_TYPES = new Set(['string', 'number', 'boolean', 'date', 'time']);
const SUPPORTED_OPERATIONS = new Set([
  'count',
  'distinct_count',
  'filtered_count',
  'filtered_rate',
  'weighted_filtered_rate',
  'sum',
  'average',
  'weighted_sum',
  'weighted_average',
  'min',
  'max',
  'variance_sample',
  'variance_population',
  'weighted_variance_sample',
  'weighted_variance_population',
  'stddev_sample',
  'stddev_population',
  'weighted_stddev_sample',
  'weighted_stddev_population',
  'median',
  'percentile',
  'mean_confidence_interval',
  'weighted_mean_confidence_interval',
  'proportion_confidence_interval',
  'weighted_proportion_confidence_interval',
]);
const WEIGHTED_OPERATIONS = new Set([
  'weighted_filtered_rate',
  'weighted_sum',
  'weighted_average',
  'weighted_variance_sample',
  'weighted_variance_population',
  'weighted_stddev_sample',
  'weighted_stddev_population',
  'weighted_mean_confidence_interval',
  'weighted_proportion_confidence_interval',
]);
const NUMERIC_SOURCE_OPERATIONS = new Set([
  'sum',
  'average',
  'weighted_sum',
  'weighted_average',
  'variance_sample',
  'variance_population',
  'weighted_variance_sample',
  'weighted_variance_population',
  'stddev_sample',
  'stddev_population',
  'weighted_stddev_sample',
  'weighted_stddev_population',
  'median',
  'percentile',
  'mean_confidence_interval',
  'weighted_mean_confidence_interval',
]);
const SEMANTIC_VIEWS = new Set([
  'survey_responses',
  'survey_topics',
  'survey_departments',
  'survey_keywords',
]);
const RESPONSE_CORE_FIELDS = {
  id: ['id', 'number'],
  survey_id: ['survey_id', 'string'],
  respondent_id: ['respondent_id', 'string'],
  reported_at: ['reported_at', 'date'],
  created_at: ['created_at', 'date'],
  updated_at: ['updated_at', 'date'],
  comment: ['comment', 'string'],
  topic_sentiment: ['topic_sentiment', 'string'],
  topic_sentiment_score: ['topic_sentiment_score', 'number'],
  cls: ['cls', 'number'],
  store_key: ['store_key', 'number'],
  store_name: ['store_name', 'string'],
  store_name_english: ['store_name_english', 'string'],
  store_name_local: ['store_name_local', 'string'],
  bu_key: ['bu_key', 'string'],
  area_manager: ['area_manager', 'string'],
  store_format: ['store_format', 'string'],
  store_type: ['store_type', 'string'],
  operations_controller: ['operations_controller', 'string'],
  regional_manager: ['regional_manager', 'string'],
  px: ['px', 'string'],
  csr: ['csr', 'string'],
  dr: ['dr', 'string'],
  mag_type: ['mag_type', 'string'],
  cf_grouping: ['cf_grouping', 'string'],
  store_brand: ['store_brand', 'string'],
  competitor: ['competitor', 'string'],
  region: ['region', 'string'],
  area: ['area', 'string'],
  province: ['province', 'string'],
  territory: ['territory', 'string'],
  toh: ['toh', 'string'],
  district: ['district', 'string'],
  city: ['city', 'string'],
  operations_manager: ['operations_manager', 'string'],
  district_manager: ['district_manager', 'string'],
  sic: ['sic', 'string'],
  soc: ['soc', 'string'],
  tech_life_type: ['tech_life_type', 'string'],
  operation_manager_tl: ['operation_manager_tl', 'string'],
  region_manager_tl: ['region_manager_tl', 'string'],
  relocation: ['relocation', 'string'],
  latitude: ['latitude', 'number'],
  longitude: ['longitude', 'number'],
  store_open_date: ['store_open_date', 'date'],
  store_close_date: ['store_close_date', 'date'],
  is_closed: ['is_closed', 'boolean'],
  channel_name: ['channel_name', 'string'],
  channel_id: ['channel_id', 'number'],
  delivery_service_name: ['delivery_service_name', 'string'],
  delivery_service_id: ['delivery_service_id', 'number'],
};
const ASSIGNMENT_RESPONSE_CORE_FIELDS = Object.fromEntries(
  Object.entries(RESPONSE_CORE_FIELDS).filter(([slug]) => slug !== 'id'),
);
const ASSIGNMENT_SHARED_CORE_FIELDS = {
  ...ASSIGNMENT_RESPONSE_CORE_FIELDS,
  assignment_id: ['assignment_id', 'number'],
  response_id: ['id', 'number'],
  sentiment: ['assignment_sentiment', 'string'],
};
const CORE_FIELDS = {
  survey_responses: RESPONSE_CORE_FIELDS,
  survey_topics: {
    ...ASSIGNMENT_SHARED_CORE_FIELDS,
    topic_id: ['topic_id', 'number'],
    topic: ['topic', 'string'],
  },
  survey_departments: {
    ...ASSIGNMENT_SHARED_CORE_FIELDS,
    department_id: ['department_id', 'number'],
    department: ['department_name', 'string'],
  },
  survey_keywords: {
    ...ASSIGNMENT_SHARED_CORE_FIELDS,
    keyword_id: ['keyword_id', 'number'],
    keyword: ['keyword', 'string'],
  },
};
const CORE_MEASURES = {
  survey_responses: new Set([
    'response_count',
    'distinct_survey_count',
    'cls_sum',
    'cls_average',
    'topic_sentiment_score_sum',
    'topic_sentiment_score_average',
    'median_topic_sentiment_score',
    'first_reported_at',
    'last_reported_at',
    'last_updated_at',
    'topic_sentiment_positive_count',
    'topic_sentiment_negative_count',
    'topic_sentiment_neutral_count',
    'topic_sentiment_mixed_count',
  ]),
  survey_topics: new Set(['assignment_count', 'distinct_survey_count', 'topic_assignment_positive_count', 'topic_assignment_negative_count', 'topic_assignment_neutral_count']),
  survey_departments: new Set(['assignment_count', 'distinct_survey_count', 'department_assignment_positive_count', 'department_assignment_negative_count', 'department_assignment_neutral_count']),
  survey_keywords: new Set(['assignment_count', 'distinct_survey_count', 'keyword_assignment_positive_count', 'keyword_assignment_negative_count', 'keyword_assignment_neutral_count']),
};

function coreFieldDescriptor(semanticView, slug) {
  const coreField = CORE_FIELDS[semanticView] && CORE_FIELDS[semanticView][slug];
  if (!coreField) return undefined;
  return {
    slug,
    label: slug.replaceAll('_', ' '),
    semanticView,
    dataType: coreField[1],
    sourceKind: 'core',
    sourceKey: null,
    visibility: 'viewer',
  };
}

function resolveCatalogField(fields, semanticView, slug) {
  if (!slug) return undefined;
  return fields.get(`${semanticView}.${slug}`) || coreFieldDescriptor(semanticView, slug);
}

function compileFieldMap(catalog, semanticView) {
  const fields = new Map(
    Object.keys(CORE_FIELDS[semanticView]).map((slug) => (
      [slug, coreFieldDescriptor(semanticView, slug)]
    )),
  );
  for (const field of catalog.fields) {
    if (field.semanticView === semanticView) fields.set(field.slug, field);
  }
  return fields;
}
const CORE_MODEL_DIR = path.join(__dirname, '..', 'model', 'core');
const CACHE_MILLISECONDS = 5_000;
const MAX_CATALOG_BYTES = 2 * 1024 * 1024;

let cachedCatalog;
let cachedCatalogHash;
let cachedAt = 0;

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(',')}}`;
  }
  return JSON.stringify(value);
}

function catalogHash(catalog) {
  return crypto.createHash('sha256').update(canonicalJson(catalog)).digest('hex');
}

function assertIdentifier(value, label) {
  if (typeof value !== 'string' || !IDENTIFIER.test(value) || value.length > 63) {
    throw new Error(`Invalid ${label} identifier`);
  }
  return value;
}

function sqlLiteral(value, maxLength = 128) {
  if (typeof value !== 'string' || value.length > maxLength || value.includes('\u0000')) {
    throw new Error('Invalid raw field source key');
  }
  let tag = 'analytics_field';
  let suffix = 0;
  while (value.includes(`$${tag}$`)) {
    suffix += 1;
    tag = `analytics_field_${suffix}`;
  }
  return `$${tag}$${value}$${tag}$`;
}

function signature(secret, timestamp, profile) {
  return crypto
    .createHmac('sha256', secret)
    .update(`${timestamp}:${profile}`)
    .digest('hex');
}

function validateCatalog(catalog, expectedProfile) {
  if (!catalog || typeof catalog !== 'object' || Array.isArray(catalog)) {
    throw new Error('Metadata response must be an object');
  }
  if (catalog.profile !== expectedProfile) {
    throw new Error('Metadata response profile does not match this Cube instance');
  }
  if (!Number.isSafeInteger(catalog.catalogVersion) || catalog.catalogVersion < 0) {
    throw new Error('Metadata catalogVersion must be a non-negative integer');
  }
  if (!Array.isArray(catalog.fields) || !Array.isArray(catalog.metrics)) {
    throw new Error('Metadata fields and metrics must be arrays');
  }
  if (catalog.rollups !== undefined && !Array.isArray(catalog.rollups)) {
    throw new Error('Metadata rollups must be an array');
  }

  const fields = new Map();
  for (const field of catalog.fields) {
    assertIdentifier(field.slug, 'field');
    if (!SEMANTIC_VIEWS.has(field.semanticView)) {
      throw new Error(`Invalid semantic view for ${field.slug}`);
    }
    if (!SUPPORTED_FIELD_TYPES.has(field.dataType)) {
      throw new Error(`Unsupported field type for ${field.slug}`);
    }
    if (!['viewer', 'admin'].includes(field.visibility)) {
      throw new Error(`Invalid field visibility for ${field.slug}`);
    }
    if (!['core', 'raw_json'].includes(field.sourceKind)) {
      throw new Error(`Invalid field source for ${field.slug}`);
    }
    if (field.sourceKind === 'raw_json') {
      sqlLiteral(field.sourceKey);
      if (CORE_FIELDS[field.semanticView][field.slug]) {
        throw new Error(`Local field ${field.slug} collides with a core field`);
      }
    } else {
      const coreField = coreFieldDescriptor(field.semanticView, field.slug);
      if (!coreField) throw new Error(`Unknown core field ${field.slug}`);
      if (coreField.dataType !== field.dataType) {
        throw new Error(`Core field ${field.slug} has an invalid type`);
      }
      if (coreField.visibility !== field.visibility) {
        throw new Error(`Core field ${field.slug} has an invalid visibility`);
      }
    }
    const fieldKey = `${field.semanticView}.${field.slug}`;
    if (fields.has(fieldKey)) {
      throw new Error(`Duplicate field ${fieldKey}`);
    }
    fields.set(fieldKey, field);
  }

  const metricNames = new Set();
  for (const metric of catalog.metrics) {
    assertIdentifier(metric.slug, 'metric');
    if (!SEMANTIC_VIEWS.has(metric.semanticView)) {
      throw new Error(`Invalid semantic view for ${metric.slug}`);
    }
    if (!SUPPORTED_OPERATIONS.has(metric.operation)) {
      throw new Error(`Unsupported metric operation for ${metric.slug}`);
    }
    if (!['viewer', 'admin'].includes(metric.visibility)) {
      throw new Error(`Invalid metric visibility for ${metric.slug}`);
    }
    if (metric.sourceField) assertIdentifier(metric.sourceField, 'metric source field');
    if (metric.weightField) assertIdentifier(metric.weightField, 'metric weight field');
    const sourceField = resolveCatalogField(fields, metric.semanticView, metric.sourceField);
    const weightField = resolveCatalogField(fields, metric.semanticView, metric.weightField);
    if (metric.sourceField && !sourceField) {
      throw new Error(`Unknown source field for ${metric.slug}`);
    }
    if (metric.operation !== 'count' && !metric.sourceField) {
      throw new Error(`Unknown source field for ${metric.slug}`);
    }
    if (NUMERIC_SOURCE_OPERATIONS.has(metric.operation) && sourceField.dataType !== 'number') {
      throw new Error(`Source field for ${metric.slug} must be numeric`);
    }
    if (['min', 'max'].includes(metric.operation)
      && !['number', 'date', 'time'].includes(sourceField.dataType)) {
      throw new Error(`Source field for ${metric.slug} cannot use ${metric.operation}`);
    }
    if (WEIGHTED_OPERATIONS.has(metric.operation) && !weightField) {
      throw new Error(`Unknown weight field for ${metric.slug}`);
    }
    if (WEIGHTED_OPERATIONS.has(metric.operation) && weightField.dataType !== 'number') {
      throw new Error(`Weight field for ${metric.slug} must be numeric`);
    }
    if (metric.visibility === 'viewer') {
      const dependencies = [sourceField, weightField].filter(Boolean);
      if (dependencies.some((field) => field.visibility !== 'viewer')) {
        throw new Error(`Viewer metric ${metric.slug} depends on an admin-only field`);
      }
    }
    if (!WEIGHTED_OPERATIONS.has(metric.operation) && metric.weightField) {
      throw new Error(`Metric ${metric.slug} does not accept a weight field`);
    }
    if (metric.operation === 'percentile') {
      const percentile = Number(metric.percentile ?? (metric.parameters && metric.parameters.percentile));
      if (!Number.isFinite(percentile) || percentile <= 0 || percentile >= 1) {
        throw new Error(`Invalid percentile for ${metric.slug}`);
      }
    }
    if (metric.operation.endsWith('confidence_interval')) {
      const confidenceLevel = Number(
        metric.confidenceLevel ?? (metric.parameters && metric.parameters.confidenceLevel),
      );
      if (!Number.isFinite(confidenceLevel) || confidenceLevel < 0.8 || confidenceLevel > 0.999) {
        throw new Error(`Invalid confidence level for ${metric.slug}`);
      }
    }
    const metricKey = `${metric.semanticView}.${metric.slug}`;
    if (metricNames.has(metricKey)) {
      throw new Error(`Duplicate metric ${metricKey}`);
    }
    metricNames.add(metricKey);
  }
  const rollupNames = new Set();
  for (const rollup of catalog.rollups || []) {
    assertIdentifier(rollup.name, 'rollup');
    if (!SEMANTIC_VIEWS.has(rollup.semanticView)) {
      throw new Error(`Invalid semantic view for rollup ${rollup.name}`);
    }
    if (!Array.isArray(rollup.measures) || rollup.measures.length < 1 || rollup.measures.length > 5) {
      throw new Error(`Rollup ${rollup.name} must contain one to five measures`);
    }
    if (!Array.isArray(rollup.dimensions) || rollup.dimensions.length > 3) {
      throw new Error(`Rollup ${rollup.name} has too many dimensions`);
    }
    rollup.measures.forEach((member) => assertIdentifier(member, 'rollup measure'));
    rollup.dimensions.forEach((member) => assertIdentifier(member, 'rollup dimension'));
    const localFields = new Map(
      [...fields.entries()]
        .filter(([key]) => key.startsWith(`${rollup.semanticView}.`))
        .map(([, field]) => [field.slug, field]),
    );
    const localMetrics = new Set(
      catalog.metrics
        .filter((metric) => metric.semanticView === rollup.semanticView)
        .map((metric) => metric.slug),
    );
    for (const dimension of rollup.dimensions) {
      if (!CORE_FIELDS[rollup.semanticView][dimension] && !localFields.has(dimension)) {
        throw new Error(`Unknown dimension ${dimension} in rollup ${rollup.name}`);
      }
    }
    for (const measure of rollup.measures) {
      if (!CORE_MEASURES[rollup.semanticView].has(measure) && !localMetrics.has(measure)) {
        throw new Error(`Unknown measure ${measure} in rollup ${rollup.name}`);
      }
    }
    if (new Set(rollup.measures).size !== rollup.measures.length
      || new Set(rollup.dimensions).size !== rollup.dimensions.length) {
      throw new Error(`Rollup ${rollup.name} contains duplicate members`);
    }
    if (rollup.timeDimension) assertIdentifier(rollup.timeDimension, 'rollup time dimension');
    if (rollup.timeDimension && !['day', 'month'].includes(rollup.granularity)) {
      throw new Error(`Rollup ${rollup.name} has an invalid granularity`);
    }
    if (!rollup.timeDimension && rollup.granularity) {
      throw new Error(`Rollup ${rollup.name} has granularity without a time dimension`);
    }
    if (rollup.timeDimension) {
      const timeField = CORE_FIELDS[rollup.semanticView][rollup.timeDimension]
        || localFields.get(rollup.timeDimension);
      const timeType = Array.isArray(timeField) ? timeField[1] : timeField && timeField.dataType;
      if (!timeField || !['date', 'time'].includes(timeType)) {
        throw new Error(`Rollup ${rollup.name} has an invalid time dimension`);
      }
    }
    if (rollup.timeDimension && !['month', 'year'].includes(rollup.partitionGranularity)) {
      throw new Error(`Rollup ${rollup.name} has an invalid partition granularity`);
    }
    if (!rollup.timeDimension && rollup.partitionGranularity != null) {
      throw new Error(`Rollup ${rollup.name} has partition granularity without a time dimension`);
    }
    if (typeof rollup.nonAdditive !== 'boolean') {
      throw new Error(`Rollup ${rollup.name} must declare nonAdditive`);
    }
    const rollupKey = `${rollup.semanticView}.${rollup.name}`;
    if (rollupNames.has(rollupKey)) throw new Error(`Duplicate rollup ${rollupKey}`);
    rollupNames.add(rollupKey);
  }
  return catalog;
}

async function fetchCatalog({ force = false } = {}) {
  const now = Date.now();
  if (!force && cachedCatalog && now - cachedAt < CACHE_MILLISECONDS) {
    return cachedCatalog;
  }

  const endpoint = process.env.ANALYTICS_METADATA_URL;
  const secret = process.env.ANALYTICS_METADATA_SECRET;
  const profile = process.env.ANALYTICS_PROFILE;
  if (!endpoint || !secret || !profile) {
    throw new Error(
      'ANALYTICS_METADATA_URL, ANALYTICS_METADATA_SECRET, and ANALYTICS_PROFILE are required',
    );
  }

  const timestamp = Math.floor(Date.now() / 1000).toString();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5_000);
  let response;
  try {
    response = await fetch(endpoint, {
      headers: {
        'Accept': 'application/json',
        'X-Analytics-Profile': profile,
        'X-Analytics-Timestamp': timestamp,
        'X-Analytics-Signature': signature(secret, timestamp, profile),
      },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new Error(`Metadata endpoint returned HTTP ${response.status}`);
  }
  const body = await response.text();
  if (Buffer.byteLength(body) > MAX_CATALOG_BYTES) {
    throw new Error('Metadata response exceeds the 2 MiB limit');
  }
  const catalog = validateCatalog(JSON.parse(body), profile);
  const nextHash = catalogHash(catalog);
  if (cachedCatalog && catalog.catalogVersion < cachedCatalog.catalogVersion) {
    throw new Error('Metadata catalogVersion moved backwards');
  }
  if (cachedCatalog && catalog.catalogVersion === cachedCatalog.catalogVersion
    && nextHash !== cachedCatalogHash) {
    throw new Error('Metadata changed without advancing catalogVersion');
  }
  cachedCatalog = catalog;
  cachedCatalogHash = nextHash;
  cachedAt = now;
  return catalog;
}

function rawExpression(field) {
  const key = sqlLiteral(field.sourceKey);
  const helper = {
    string: 'analytics_raw_value',
    number: 'analytics_raw_number',
    boolean: 'analytics_raw_boolean',
    date: 'analytics_raw_timestamp',
    time: 'analytics_raw_time',
  }[field.dataType];
  return `${helper}({CUBE}.raw_row_data, ${key})`;
}

function fieldExpression(field) {
  if (field.sourceKind === 'raw_json') return rawExpression(field);
  const coreField = CORE_FIELDS[field.semanticView] && CORE_FIELDS[field.semanticView][field.slug];
  if (!coreField) throw new Error(`Unknown core field ${field.slug}`);
  return `{CUBE}.${coreField[0]}`;
}

function dimensionExpression(field) {
  const expression = fieldExpression(field);
  // PostgreSQL cannot date_trunc a time-without-time-zone value. Anchor a
  // promoted time-of-day to a fixed date only for Cube time-dimension
  // grouping; filters and min/max measures continue to use the native time.
  return field.dataType === 'time'
    ? `(DATE '2000-01-01' + (${expression}))`
    : expression;
}

function yamlScalar(value) {
  return JSON.stringify(String(value));
}

function typedSqlLiteral(value, field) {
  if (value === null) throw new Error('Use is_null or is_not_null for null filters');
  if (field.dataType === 'number') {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) throw new Error('Filter value must be finite');
    return String(numeric);
  }
  if (field.dataType === 'boolean') {
    if (value !== true && value !== false) throw new Error('Filter value must be boolean');
    return value ? 'TRUE' : 'FALSE';
  }
  if (typeof value !== 'string' || value.length > 500) {
    throw new Error('Filter value must be a bounded string');
  }
  return sqlLiteral(value, 500);
}

function filterPredicate(metric, fields) {
  const field = fields.get(metric.sourceField);
  const expression = fieldExpression(field);
  const filter = metric.parameters && metric.parameters.filter;
  if (!filter || typeof filter !== 'object' || Array.isArray(filter)) {
    throw new Error(`Filtered metric ${metric.slug} requires a structured filter`);
  }
  switch (filter.operator) {
    case 'equals': return `${expression} = ${typedSqlLiteral(filter.value, field)}`;
    case 'not_equals': return `${expression} <> ${typedSqlLiteral(filter.value, field)}`;
    case 'greater_than': return `${expression} > ${typedSqlLiteral(filter.value, field)}`;
    case 'greater_than_or_equal': return `${expression} >= ${typedSqlLiteral(filter.value, field)}`;
    case 'less_than': return `${expression} < ${typedSqlLiteral(filter.value, field)}`;
    case 'less_than_or_equal': return `${expression} <= ${typedSqlLiteral(filter.value, field)}`;
    case 'is_null': return `${expression} IS NULL`;
    case 'is_not_null': return `${expression} IS NOT NULL`;
    case 'in': {
      if (!Array.isArray(filter.values) || filter.values.length < 1 || filter.values.length > 100) {
        throw new Error(`Filtered metric ${metric.slug} has an invalid values list`);
      }
      return `${expression} IN (${filter.values.map((value) => typedSqlLiteral(value, field)).join(', ')})`;
    }
    default: throw new Error(`Filtered metric ${metric.slug} has an invalid operator`);
  }
}

function invalidNumber(expression) {
  return `(${expression}) = 'NaN'::double precision OR (${expression}) = 'Infinity'::double precision OR (${expression}) = '-Infinity'::double precision`;
}

function invalidNumericField(field, expression) {
  if (field && field.sourceKind === 'raw_json') {
    return `analytics_raw_number_invalid({CUBE}.raw_row_data, ${sqlLiteral(field.sourceKey)})`;
  }
  return invalidNumber(expression);
}

function weightedParts(source, weight, numericSource = true, sourceField, weightField) {
  const invalidWeight = `(${weight}) < 0 OR ${invalidNumericField(weightField, weight)}`;
  const invalidValue = numericSource ? invalidNumericField(sourceField, source) : 'FALSE';
  const sourcePresent = numericSource
    ? `((${source}) IS NOT NULL OR (${invalidValue}))`
    : `((${source}) IS NOT NULL)`;
  const weightPresent = `((${weight}) IS NOT NULL OR (${invalidNumericField(weightField, weight)}))`;
  const pair = `(${sourcePresent} AND ${weightPresent})`;
  const invalid = `((${pair}) AND (${invalidWeight} OR ${invalidValue}))`;
  const valid = `((${source}) IS NOT NULL AND (${weight}) IS NOT NULL AND NOT (${invalidWeight}) AND NOT (${invalidValue}))`;
  const invalidWeightRow = `((${pair}) AND (${invalidWeight}))`;
  const invalidValueRow = `((${pair}) AND (${invalidValue}))`;
  const sumW = `SUM(CASE WHEN ${valid} THEN (${weight}) END)`;
  const sumW2 = `SUM(CASE WHEN ${valid} THEN (${weight}) * (${weight}) END)`;
  const sumWX = numericSource
    ? `SUM(CASE WHEN ${valid} THEN (${weight}) * (${source}) END)`
    : `SUM(CASE WHEN ${valid} THEN 0.0 END)`;
  const sumWX2 = numericSource
    ? `SUM(CASE WHEN ${valid} THEN (${weight}) * (${source}) * (${source}) END)`
    : `SUM(CASE WHEN ${valid} THEN 0.0 END)`;
  const invalidCount = `SUM(CASE WHEN ${invalid} THEN 1 ELSE 0 END)`;
  const populationVariance = `((${sumWX2}) / NULLIF((${sumW}), 0) - POWER((${sumWX}) / NULLIF((${sumW}), 0), 2))`;
  const sampleVariance = `((${sumWX2}) - POWER((${sumWX}), 2) / NULLIF((${sumW}), 0)) / NULLIF((${sumW}) - (${sumW2}) / NULLIF((${sumW}), 0), 0)`;
  return {
    valid,
    invalid,
    invalidWeight,
    invalidValue,
    invalidWeightRow,
    invalidValueRow,
    invalidCount,
    sumW,
    sumW2,
    sumWX,
    sumWX2,
    populationVariance,
    sampleVariance,
  };
}

function compileDimension(field) {
  const cubeType = field.dataType === 'date' || field.dataType === 'time'
    ? 'time'
    : field.dataType;
  return [
    `      - name: ${field.slug}`,
    `        title: ${yamlScalar(field.label || field.slug)}`,
    `        sql: ${yamlScalar(dimensionExpression(field))}`,
    `        type: ${cubeType}`,
  ].join('\n');
}

function metricSql(metric, fields) {
  const source = metric.sourceField ? fieldExpression(fields.get(metric.sourceField)) : null;
  const weight = metric.weightField ? fieldExpression(fields.get(metric.weightField)) : null;
  const sourceField = metric.sourceField ? fields.get(metric.sourceField) : null;
  const weightField = metric.weightField ? fields.get(metric.weightField) : null;
  const numericWeightedSource = ![
    'weighted_filtered_rate',
    'weighted_proportion_confidence_interval',
  ].includes(metric.operation);
  const weighted = weight
    ? weightedParts(source, weight, numericWeightedSource, sourceField, weightField)
    : null;
  const nullOnInvalid = (sql) => `CASE WHEN (${weighted.invalidCount}) > 0 THEN NULL ELSE ${sql} END`;
  switch (metric.operation) {
    case 'count': return source
      ? { type: 'number', sql: `COUNT(${source})` }
      : { type: 'count' };
    case 'distinct_count': return { type: 'count_distinct', sql: source };
    case 'filtered_count':
      return { type: 'number', sql: `SUM(CASE WHEN ${filterPredicate(metric, fields)} THEN 1 ELSE 0 END)` };
    case 'filtered_rate':
    case 'proportion_confidence_interval': {
      const predicate = filterPredicate(metric, fields);
      return {
        type: 'number',
        sql: `SUM(CASE WHEN (${source}) IS NOT NULL AND (${predicate}) THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(${source}), 0)`,
      };
    }
    case 'weighted_filtered_rate':
    case 'weighted_proportion_confidence_interval': {
      const predicate = filterPredicate(metric, fields);
      const numerator = `SUM(CASE WHEN ${weighted.valid} AND (${predicate}) THEN (${weight}) ELSE 0 END)`;
      return { type: 'number', sql: nullOnInvalid(`(${numerator}) / NULLIF((${weighted.sumW}), 0)`) };
    }
    case 'sum': return { type: 'sum', sql: source };
    case 'average': return { type: 'avg', sql: source };
    case 'min':
      return ['date', 'time'].includes(sourceField.dataType)
        ? { type: 'time', sql: `MIN(${source})` }
        : { type: 'min', sql: source };
    case 'max':
      return ['date', 'time'].includes(sourceField.dataType)
        ? { type: 'time', sql: `MAX(${source})` }
        : { type: 'max', sql: source };
    case 'weighted_sum':
      return { type: 'number', sql: nullOnInvalid(weighted.sumWX) };
    case 'weighted_average':
    case 'weighted_mean_confidence_interval':
      return {
        type: 'number',
        sql: nullOnInvalid(`(${weighted.sumWX}) / NULLIF((${weighted.sumW}), 0)`),
      };
    case 'variance_sample': return { type: 'number', sql: `VAR_SAMP(${source})` };
    case 'variance_population': return { type: 'number', sql: `VAR_POP(${source})` };
    case 'stddev_sample': return { type: 'number', sql: `STDDEV_SAMP(${source})` };
    case 'stddev_population': return { type: 'number', sql: `STDDEV_POP(${source})` };
    case 'weighted_variance_sample':
      return { type: 'number', sql: nullOnInvalid(weighted.sampleVariance) };
    case 'weighted_variance_population':
      return { type: 'number', sql: nullOnInvalid(weighted.populationVariance) };
    case 'weighted_stddev_sample':
      return { type: 'number', sql: nullOnInvalid(`SQRT(GREATEST(${weighted.sampleVariance}, 0))`) };
    case 'weighted_stddev_population':
      return { type: 'number', sql: nullOnInvalid(`SQRT(GREATEST(${weighted.populationVariance}, 0))`) };
    case 'median':
      return {
        type: 'number',
        sql: `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ${source})`,
      };
    case 'percentile': {
      const percentile = Number(metric.percentile ?? (metric.parameters && metric.parameters.percentile));
      if (!Number.isFinite(percentile) || percentile <= 0 || percentile >= 1) {
        throw new Error(`Invalid percentile for ${metric.slug}`);
      }
      return {
        type: 'number',
        sql: `PERCENTILE_CONT(${percentile}) WITHIN GROUP (ORDER BY ${source})`,
      };
    }
    case 'mean_confidence_interval': return { type: 'avg', sql: source };
    default: throw new Error(`Unsupported metric operation for ${metric.slug}`);
  }
}

function compileMeasureDefinition(name, title, definition) {
  const result = [
    `      - name: ${name}`,
    `        title: ${yamlScalar(title)}`,
    `        type: ${definition.type}`,
  ];
  if (definition.sql) {
    result.push(`        sql: ${yamlScalar(definition.sql)}`);
  }
  return result.join('\n');
}

function supportingMeasures(metric, fields) {
  const source = metric.sourceField ? fieldExpression(fields.get(metric.sourceField)) : null;
  const weight = metric.weightField ? fieldExpression(fields.get(metric.weightField)) : null;
  const sourceField = metric.sourceField ? fields.get(metric.sourceField) : null;
  const weightField = metric.weightField ? fields.get(metric.weightField) : null;
  const definitions = [];
  const add = (suffix, sql) => definitions.push({
    name: `${metric.slug}__${suffix}`,
    title: `${metric.label || metric.slug} ${suffix.replaceAll('_', ' ')}`,
    definition: { type: 'number', sql },
  });

  if (WEIGHTED_OPERATIONS.has(metric.operation)) {
    const numericWeightedSource = ![
      'weighted_filtered_rate',
      'weighted_proportion_confidence_interval',
    ].includes(metric.operation);
    const parts = weightedParts(
      source,
      weight,
      numericWeightedSource,
      sourceField,
      weightField,
    );
    add('invalid_weight_count', `SUM(CASE WHEN ${parts.invalidWeightRow} THEN 1 ELSE 0 END)`);
    add('invalid_value_count', `SUM(CASE WHEN ${parts.invalidValueRow} THEN 1 ELSE 0 END)`);
    add('pair_count', `SUM(CASE WHEN ${parts.valid} THEN 1 ELSE 0 END)`);
    add('weight_sum', parts.sumW);
    add('weight_sum_squares', parts.sumW2);
    add('weighted_value_sum', parts.sumWX);
    add('weighted_value_square_sum', parts.sumWX2);
    if (['weighted_filtered_rate', 'weighted_proportion_confidence_interval'].includes(metric.operation)) {
      const predicate = filterPredicate(metric, fields);
      add('success_weight_sum', `SUM(CASE WHEN ${parts.valid} AND (${predicate}) THEN (${weight}) ELSE 0 END)`);
    }
  }
  if (metric.operation === 'mean_confidence_interval') {
    add('sample_count', `COUNT(${source})`);
    add('value_sum', `SUM(${source})`);
    add('value_square_sum', `SUM((${source}) * (${source}))`);
    add('variance_sample', `VAR_SAMP(${source})`);
  }
  if (metric.operation === 'proportion_confidence_interval') {
    const predicate = filterPredicate(metric, fields);
    add('success_count', `SUM(CASE WHEN (${source}) IS NOT NULL AND (${predicate}) THEN 1 ELSE 0 END)`);
    add('sample_count', `COUNT(${source})`);
  }
  return definitions;
}

function compileMeasures(metric, fields) {
  const main = {
    name: metric.slug,
    title: metric.label || metric.slug,
    definition: metricSql(metric, fields),
  };
  return [main, ...supportingMeasures(metric, fields)].map((item) => (
    compileMeasureDefinition(item.name, item.title, item.definition)
  ));
}

function compileMeasure(metric, fields) {
  return compileMeasures(metric, fields)[0];
}

function metricSupportSuffixes(metric) {
  const suffixes = [];
  if (WEIGHTED_OPERATIONS.has(metric.operation)) {
    suffixes.push(
      'invalid_weight_count',
      'invalid_value_count',
      'pair_count',
      'weight_sum',
      'weight_sum_squares',
      'weighted_value_sum',
      'weighted_value_square_sum',
    );
    if (['weighted_filtered_rate', 'weighted_proportion_confidence_interval'].includes(metric.operation)) {
      suffixes.push('success_weight_sum');
    }
  }
  if (metric.operation === 'mean_confidence_interval') {
    suffixes.push('sample_count', 'value_sum', 'value_square_sum', 'variance_sample');
  } else if (metric.operation === 'proportion_confidence_interval') {
    suffixes.push('success_count', 'sample_count');
  }
  return suffixes;
}

function compileRollup(rollup, metrics = []) {
  const metricBySlug = new Map(metrics.map((metric) => [metric.slug, metric]));
  const materializedMeasures = rollup.measures.flatMap((member) => {
    const metric = metricBySlug.get(member);
    return [
      member,
      ...metricSupportSuffixes(metric || {}).map((suffix) => `${member}__${suffix}`),
    ];
  });
  const result = [
    `      - name: ${rollup.name}`,
    '        type: rollup',
    '        measures:',
    ...materializedMeasures.map((member) => `          - ${member}`),
  ];
  if (rollup.dimensions.length) {
    result.push(
      '        dimensions:',
      ...rollup.dimensions.map((member) => `          - ${member}`),
    );
  }
  if (rollup.timeDimension) {
    result.push(
      `        time_dimension: ${rollup.timeDimension}`,
      `        granularity: ${rollup.granularity}`,
      `        partition_granularity: ${rollup.partitionGranularity}`,
    );
  }
  result.push(
    '        scheduled_refresh: true',
    '        refresh_key:',
    '          every: 15 minute',
  );
  return result.join('\n');
}

function injectCatalog(core, catalog, semanticView = 'survey_responses') {
  const fields = compileFieldMap(catalog, semanticView);
  const dimensions = catalog.fields
    .filter((field) => field.semanticView === semanticView && field.sourceKind === 'raw_json')
    .map(compileDimension)
    .join('\n');
  const measures = catalog.metrics
    .filter((metric) => metric.semanticView === semanticView)
    .flatMap((metric) => compileMeasures(metric, fields))
    .join('\n');
  const rollups = (catalog.rollups || [])
    .filter((rollup) => rollup.semanticView === semanticView)
    .map((rollup) => compileRollup(
      rollup,
      catalog.metrics.filter((metric) => metric.semanticView === semanticView),
    ))
    .join('\n');
  return core
    .replace('      # __LOCAL_DIMENSIONS__', dimensions || '      # no published local dimensions')
    .replace('      # __LOCAL_MEASURES__', measures || '      # no published local measures')
    .replace('      # __LOCAL_PREAGGREGATIONS__', rollups || '      # no published chart rollups');
}

function coreFiles() {
  return fs.readdirSync(CORE_MODEL_DIR)
    .filter((fileName) => fileName.endsWith('.yml'))
    .sort()
    .map((fileName) => ({
      fileName: `core/${fileName}`,
      content: fs.readFileSync(path.join(CORE_MODEL_DIR, fileName), 'utf8'),
    }));
}

function catalogRepository() {
  return {
    dataSchemaFiles: async () => {
      const catalog = await fetchCatalog();
      return coreFiles().map((file) => {
        const semanticView = path.basename(file.fileName, '.yml');
        return { ...file, content: injectCatalog(file.content, catalog, semanticView) };
      });
    },
  };
}

async function catalogVersion() {
  const catalog = await fetchCatalog({ force: true });
  return `${catalog.profile}:${catalog.catalogVersion}`;
}

function filterMembers(filters, depth = 0, budget = { remaining: 200 }) {
  if (depth > 12 || budget.remaining <= 0) {
    throw new Error('Cube filter tree exceeds the security validation limit');
  }
  if (Array.isArray(filters)) {
    return filters.flatMap((item) => filterMembers(item, depth, budget));
  }
  if (!filters || typeof filters !== 'object') return [];
  budget.remaining -= 1;
  const members = [];
  if (typeof filters.member === 'string') members.push(filters.member);
  if (typeof filters.dimension === 'string') members.push(filters.dimension);
  if (filters.and) members.push(...filterMembers(filters.and, depth + 1, budget));
  if (filters.or) members.push(...filterMembers(filters.or, depth + 1, budget));
  return members;
}

function orderMembers(order) {
  if (Array.isArray(order)) {
    return order.flatMap((item) => (
      Array.isArray(item) && typeof item[0] === 'string' ? [item[0]] : []
    ));
  }
  if (order && typeof order === 'object') return Object.keys(order);
  return [];
}

function queryMembers(query) {
  const timeDimensions = (query.timeDimensions || []).map((item) => item.dimension);
  return [
    ...(query.measures || []),
    ...(query.dimensions || []),
    ...timeDimensions,
    ...filterMembers(query.filters || []),
    ...orderMembers(query.order),
  ].filter(Boolean);
}

async function enforceSecurityContext(query, { securityContext } = {}) {
  const profile = process.env.ANALYTICS_PROFILE;
  const tokenProfile = securityContext && (
    securityContext.profile
    || securityContext.profile_id
    || (securityContext.securityContext && securityContext.securityContext.profile)
  );
  if (tokenProfile !== profile) {
    throw new Error('Cube token is not scoped to this analytics profile');
  }
  const tokenRole = securityContext && (
    securityContext.role
    || (securityContext.securityContext && securityContext.securityContext.role)
  );
  const role = ['admin', 'refresh_worker'].includes(tokenRole) ? 'admin' : 'viewer';
  const catalog = await fetchCatalog();
  const restricted = new Set([
    ...catalog.fields.filter((item) => item.visibility === 'admin').map((item) => item.slug),
    ...catalog.metrics.filter((item) => item.visibility === 'admin').map((item) => item.slug),
  ]);
  const members = queryMembers(query);
  if (role !== 'admin' && members.some((member) => {
    const slug = member.split('.').at(-1).split('__', 1)[0];
    return restricted.has(slug);
  })) {
    throw new Error('Cube member is not visible to this role');
  }
  const semanticViews = new Set(
    members.map((member) => member.split('.')[0]).filter((view) => SEMANTIC_VIEWS.has(view)),
  );
  if (semanticViews.size > 1) {
    throw new Error('A query must use exactly one semantic view');
  }
  return query;
}

module.exports = {
  catalogRepository,
  catalogVersion,
  compileDimension,
  compileMeasure,
  compileMeasures,
  compileRollup,
  enforceSecurityContext,
  injectCatalog,
  signature,
  sqlLiteral,
  validateCatalog,
};
