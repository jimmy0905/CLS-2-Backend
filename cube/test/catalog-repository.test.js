'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');

const {
  compileDimension,
  compileMeasure,
  compileMeasures,
  compileRollup,
  catalogVersion,
  contextToApiScopes,
  enforceSecurityContext,
  injectCatalog,
  signature,
  sqlLiteral,
  validateCatalog,
} = require('../lib/catalog-repository');

const profile = 'wtchk_cls';

function catalog(overrides = {}) {
  return {
    profile,
    catalogVersion: 1,
    fields: [
      {
        slug: 'survey_weight',
        label: 'Survey weight',
        semanticView: 'survey_responses',
        dataType: 'number',
        sourceKind: 'raw_json',
        sourceKey: 'Survey Weight',
        visibility: 'viewer',
      },
      {
        slug: 'private_note',
        label: 'Private note',
        semanticView: 'survey_responses',
        dataType: 'string',
        sourceKind: 'raw_json',
        sourceKey: 'Private Note',
        visibility: 'admin',
      },
      {
        slug: 'score',
        label: 'Score',
        semanticView: 'survey_responses',
        dataType: 'number',
        sourceKind: 'raw_json',
        sourceKey: "Score's value",
        visibility: 'viewer',
      },
    ],
    metrics: [],
    ...overrides,
  };
}

test('request signature matches the backend timestamp:profile contract', () => {
  const secret = 'metadata-secret';
  const timestamp = '1777000000';
  const expected = crypto
    .createHmac('sha256', secret)
    .update(`${timestamp}:${profile}`)
    .digest('hex');

  assert.equal(signature(secret, timestamp, profile), expected);
});

test('only refresh workers receive the pre-aggregation jobs API scope', () => {
  const defaultScopes = ['graphql', 'meta', 'data', 'sql'];

  assert.deepEqual(
    contextToApiScopes({ profile, role: 'viewer' }, defaultScopes),
    defaultScopes,
  );
  assert.deepEqual(
    contextToApiScopes({ profile, role: 'admin' }, defaultScopes),
    defaultScopes,
  );
  assert.deepEqual(
    contextToApiScopes({ profile, role: 'refresh_worker' }, defaultScopes),
    [...defaultScopes, 'jobs'],
  );
  assert.deepEqual(
    contextToApiScopes({ securityContext: { role: 'refresh_worker' } }, defaultScopes),
    [...defaultScopes, 'jobs'],
  );
});

test('empty bootstrap catalog uses version zero before first publication', () => {
  const bootstrap = catalog({ catalogVersion: 0, fields: [], metrics: [] });

  assert.equal(validateCatalog(bootstrap, profile).catalogVersion, 0);
});

test('raw source keys are SQL literals and cannot become identifiers', () => {
  assert.equal(
    sqlLiteral("Score's value"),
    "$analytics_field$Score's value$analytics_field$",
  );
  assert.equal(
    sqlLiteral("\\'; SELECT pg_sleep(10); --"),
    "$analytics_field$\\'; SELECT pg_sleep(10); --$analytics_field$",
  );
  assert.equal(
    sqlLiteral('$analytics_field$collision'),
    '$analytics_field_1$$analytics_field$collision$analytics_field_1$',
  );
  assert.throws(() => sqlLiteral(`bad\u0000key`), /Invalid raw field source key/);
});

test('catalog validation rejects unsafe identifiers and unknown weights', () => {
  const unsafe = catalog();
  unsafe.fields[0].slug = 'score); DROP TABLE surveys;--';
  assert.throws(() => validateCatalog(unsafe, profile), /Invalid field identifier/);

  const unknownWeight = catalog({
    metrics: [
      {
        slug: 'weighted_score',
        label: 'Weighted score',
        semanticView: 'survey_responses',
        operation: 'weighted_average',
        sourceField: 'score',
        weightField: 'missing',
        visibility: 'viewer',
      },
    ],
  });
  assert.throws(() => validateCatalog(unknownWeight, profile), /Unknown weight field/);

  const hiddenDependency = catalog({
    metrics: [
      {
        slug: 'private_note_count',
        label: 'Private note count',
        semanticView: 'survey_responses',
        operation: 'distinct_count',
        sourceField: 'private_note',
        visibility: 'viewer',
      },
    ],
  });
  assert.throws(
    () => validateCatalog(hiddenDependency, profile),
    /depends on an admin-only field/,
  );
});

test('compiler emits typed helper calls and stable PostgreSQL percentiles', () => {
  const value = catalog().fields.find((field) => field.slug === 'score');
  assert.match(compileDimension(value), /analytics_raw_number/);
  assert.match(compileDimension(value), /Score's value/);

  const fields = new Map(catalog().fields.map((field) => [field.slug, field]));
  const percentile = compileMeasure(
    {
      slug: 'score_p90',
      label: 'Score p90',
      semanticView: 'survey_responses',
      operation: 'percentile',
      sourceField: 'score',
      parameters: { percentile: 0.9 },
      visibility: 'viewer',
    },
    fields,
  );
  assert.match(percentile, /PERCENTILE_CONT\(0.9\) WITHIN GROUP/);
  assert.match(percentile, /type: number/);
  assert.doesNotMatch(percentile, /number_agg/);

  const nonNullCount = compileMeasure(
    {
      slug: 'score_count',
      label: 'Scores present',
      semanticView: 'survey_responses',
      operation: 'count',
      sourceField: 'score',
      visibility: 'viewer',
    },
    fields,
  );
  assert.match(nonNullCount, /COUNT\(analytics_raw_number\(/);
  assert.match(nonNullCount, /type: number/);

  const timestamp = compileDimension({
    slug: 'visit_started_at',
    label: 'Visit started at',
    semanticView: 'survey_responses',
    dataType: 'date',
    sourceKind: 'raw_json',
    sourceKey: 'Visit Started At',
    visibility: 'viewer',
  });
  assert.match(timestamp, /analytics_raw_timestamp/);
  assert.doesNotMatch(timestamp, /analytics_raw_date/);

  const timeOfDay = compileDimension({
    slug: 'visit_time',
    label: 'Visit time',
    semanticView: 'survey_responses',
    dataType: 'time',
    sourceKind: 'raw_json',
    sourceKey: 'Visit Time',
    visibility: 'viewer',
  });
  assert.match(timeOfDay, /DATE '2000-01-01'/);
  assert.match(timeOfDay, /analytics_raw_time/);
});

test('published local members are inserted without evaluating metadata as code', () => {
  const core = [
    '    measures:',
    '      # __LOCAL_MEASURES__',
    '    dimensions:',
    '      # __LOCAL_DIMENSIONS__',
  ].join('\n');
  const localCatalog = catalog({
    metrics: [
      {
        slug: 'average_score',
        label: 'Average score',
        semanticView: 'survey_responses',
        operation: 'average',
        sourceField: 'score',
        visibility: 'viewer',
      },
    ],
  });
  const result = injectCatalog(core, validateCatalog(localCatalog, profile));

  assert.match(result, /name: average_score/);
  assert.match(result, /name: score/);
  assert.match(result, /type: avg/);
});

test('metrics resolve fixed core sources and weights without catalog field duplication', () => {
  const assignmentViews = [
    'survey_topics',
    'survey_departments',
    'survey_keywords',
  ];
  const coreMetrics = (semanticView, weightField) => [
    {
      slug: 'average_cls',
      label: 'Average CLS',
      semanticView,
      operation: 'average',
      sourceField: 'cls',
      visibility: 'viewer',
    },
    {
      slug: 'distinct_store_name',
      label: 'Distinct stores',
      semanticView,
      operation: 'distinct_count',
      sourceField: 'store_name',
      visibility: 'viewer',
    },
    {
      slug: 'earliest_reported_at',
      label: 'Earliest response',
      semanticView,
      operation: 'min',
      sourceField: 'reported_at',
      visibility: 'viewer',
    },
    {
      slug: 'latest_reported_at',
      label: 'Latest response',
      semanticView,
      operation: 'max',
      sourceField: 'reported_at',
      visibility: 'viewer',
    },
    {
      slug: 'weighted_cls',
      label: 'Weighted CLS',
      semanticView,
      operation: 'weighted_average',
      sourceField: 'cls',
      weightField,
      visibility: 'viewer',
    },
  ];
  const localCatalog = validateCatalog({
    profile,
    catalogVersion: 2,
    fields: [],
    metrics: [
      ...coreMetrics('survey_responses', 'id'),
      ...assignmentViews.flatMap((semanticView) => (
        coreMetrics(semanticView, 'response_id')
      )),
    ],
  }, profile);
  const core = [
    '    measures:',
    '      # __LOCAL_MEASURES__',
    '    dimensions:',
    '      # __LOCAL_DIMENSIONS__',
  ].join('\n');
  const responses = injectCatalog(core, localCatalog, 'survey_responses');
  const assignments = assignmentViews.map((semanticView) => (
    injectCatalog(core, localCatalog, semanticView)
  ));

  for (const compiled of [responses, ...assignments]) {
    assert.match(compiled, /name: average_cls[\s\S]*?type: avg/);
    assert.match(compiled, /name: distinct_store_name[\s\S]*?\{CUBE\}\.store_name/);
    assert.match(compiled, /name: earliest_reported_at[\s\S]*?type: time[\s\S]*?MIN\(\{CUBE\}\.reported_at\)/);
    assert.match(compiled, /name: latest_reported_at[\s\S]*?type: time[\s\S]*?MAX\(\{CUBE\}\.reported_at\)/);
  }
  assert.match(responses, /name: weighted_cls[\s\S]*?\{CUBE\}\.id/);
  for (const compiled of assignments) {
    assert.match(compiled, /name: weighted_cls[\s\S]*?\{CUBE\}\.id/);
  }
});

test('core source descriptors enforce type and visibility invariants', () => {
  assert.throws(
    () => validateCatalog({
      profile,
      catalogVersion: 1,
      fields: [],
      metrics: [{
        slug: 'invalid_store_average',
        label: 'Invalid store average',
        semanticView: 'survey_responses',
        operation: 'average',
        sourceField: 'store_name',
        visibility: 'viewer',
      }],
    }, profile),
    /must be numeric/,
  );
  assert.throws(
    () => validateCatalog({
      profile,
      catalogVersion: 1,
      fields: [{
        slug: 'cls',
        label: 'CLS',
        semanticView: 'survey_responses',
        dataType: 'number',
        sourceKind: 'core',
        sourceKey: null,
        visibility: 'admin',
      }],
      metrics: [],
    }, profile),
    /invalid visibility/,
  );
});

test('weighted confidence metrics publish Kish components and visible data-quality counts', () => {
  const localCatalog = validateCatalog(catalog({
    metrics: [
      {
        slug: 'weighted_score_ci',
        label: 'Weighted score interval',
        semanticView: 'survey_responses',
        operation: 'weighted_mean_confidence_interval',
        sourceField: 'score',
        weightField: 'survey_weight',
        confidenceLevel: 0.95,
        visibility: 'viewer',
      },
    ],
  }), profile);
  const fields = new Map(localCatalog.fields.map((field) => [field.slug, field]));
  const measures = compileMeasures(localCatalog.metrics[0], fields).join('\n');

  assert.match(measures, /weighted_score_ci__invalid_weight_count/);
  assert.match(measures, /weighted_score_ci__invalid_value_count/);
  assert.match(measures, /weighted_score_ci__weight_sum/);
  assert.match(measures, /weighted_score_ci__weight_sum_squares/);
  assert.match(measures, /weighted_score_ci__weighted_value_square_sum/);
  assert.match(measures, /< 0/);
  assert.match(measures, /analytics_raw_number_invalid/);
  assert.match(measures, /Survey Weight/);
  assert.match(measures, /Score's value/);
  assert.match(
    measures,
    /IS NOT NULL OR \(analytics_raw_number_invalid/,
  );
});

test('proportion intervals publish success and sample aggregates from structured filters', () => {
  const localCatalog = validateCatalog(catalog({
    metrics: [
      {
        slug: 'positive_rate_ci',
        label: 'Positive rate interval',
        semanticView: 'survey_responses',
        operation: 'proportion_confidence_interval',
        sourceField: 'score',
        confidenceLevel: 0.9,
        parameters: {
          filter: { operator: 'greater_than_or_equal', value: 4 },
        },
        visibility: 'viewer',
      },
    ],
  }), profile);
  const fields = new Map(localCatalog.fields.map((field) => [field.slug, field]));
  const measures = compileMeasures(localCatalog.metrics[0], fields).join('\n');

  assert.match(measures, /positive_rate_ci__success_count/);
  assert.match(measures, /positive_rate_ci__sample_count/);
  assert.match(measures, />= 4/);
  assert.match(measures, /COUNT\(analytics_raw_number\(/);
  assert.doesNotMatch(measures, /COUNT\(\*\)/);
});

test('core field registry resolves assignment aliases and rejects type drift', () => {
  const coreSentiment = {
    slug: 'sentiment',
    label: 'Assignment sentiment',
    semanticView: 'survey_departments',
    dataType: 'string',
    sourceKind: 'core',
    sourceKey: null,
    visibility: 'viewer',
  };
  const localCatalog = validateCatalog({
    profile,
    catalogVersion: 1,
    fields: [coreSentiment],
    metrics: [
      {
        slug: 'sentiment_distinct',
        label: 'Distinct sentiments',
        semanticView: 'survey_departments',
        operation: 'distinct_count',
        sourceField: 'sentiment',
        visibility: 'viewer',
      },
    ],
  }, profile);
  const fields = new Map(localCatalog.fields.map((field) => [field.slug, field]));
  assert.match(
    compileMeasure(localCatalog.metrics[0], fields),
    /\{CUBE\}\.assignment_sentiment/,
  );

  assert.throws(
    () => validateCatalog({
      ...localCatalog,
      fields: [{ ...coreSentiment, dataType: 'number' }],
    }, profile),
    /invalid type/,
  );
});

test('date and time extrema compile as temporal aggregate measures', () => {
  const dateField = {
    slug: 'reported_at',
    label: 'Reported at',
    semanticView: 'survey_responses',
    dataType: 'date',
    sourceKind: 'core',
    sourceKey: null,
    visibility: 'viewer',
  };
  const numberField = catalog().fields.find((field) => field.slug === 'score');
  const fields = new Map([
    [dateField.slug, dateField],
    [numberField.slug, numberField],
  ]);
  const earliest = compileMeasure({
    slug: 'earliest_response',
    label: 'Earliest response',
    operation: 'min',
    sourceField: 'reported_at',
  }, fields);
  const largest = compileMeasure({
    slug: 'largest_score',
    label: 'Largest score',
    operation: 'max',
    sourceField: 'score',
  }, fields);

  assert.match(earliest, /type: time/);
  assert.match(earliest, /MIN\(\{CUBE\}\.reported_at\)/);
  assert.match(largest, /type: max/);
  assert.doesNotMatch(largest, /MAX\(/);
});

test('the compiler covers every published aggregation operation', () => {
  const base = {
    label: 'Operation metric',
    semanticView: 'survey_responses',
    sourceField: 'score',
    visibility: 'viewer',
  };
  const filter = { filter: { operator: 'greater_than', value: 0 } };
  const metrics = [
    { ...base, slug: 'op_count', operation: 'count', sourceField: null },
    { ...base, slug: 'op_distinct', operation: 'distinct_count' },
    { ...base, slug: 'op_filtered_count', operation: 'filtered_count', parameters: filter },
    { ...base, slug: 'op_filtered_rate', operation: 'filtered_rate', parameters: filter },
    { ...base, slug: 'op_weighted_rate', operation: 'weighted_filtered_rate', weightField: 'survey_weight', parameters: filter },
    { ...base, slug: 'op_sum', operation: 'sum' },
    { ...base, slug: 'op_average', operation: 'average' },
    { ...base, slug: 'op_weighted_sum', operation: 'weighted_sum', weightField: 'survey_weight' },
    { ...base, slug: 'op_weighted_average', operation: 'weighted_average', weightField: 'survey_weight' },
    { ...base, slug: 'op_min', operation: 'min' },
    { ...base, slug: 'op_max', operation: 'max' },
    { ...base, slug: 'op_var_samp', operation: 'variance_sample' },
    { ...base, slug: 'op_var_pop', operation: 'variance_population' },
    { ...base, slug: 'op_weighted_var_samp', operation: 'weighted_variance_sample', weightField: 'survey_weight' },
    { ...base, slug: 'op_weighted_var_pop', operation: 'weighted_variance_population', weightField: 'survey_weight' },
    { ...base, slug: 'op_std_samp', operation: 'stddev_sample' },
    { ...base, slug: 'op_std_pop', operation: 'stddev_population' },
    { ...base, slug: 'op_weighted_std_samp', operation: 'weighted_stddev_sample', weightField: 'survey_weight' },
    { ...base, slug: 'op_weighted_std_pop', operation: 'weighted_stddev_population', weightField: 'survey_weight' },
    { ...base, slug: 'op_median', operation: 'median' },
    { ...base, slug: 'op_percentile', operation: 'percentile', parameters: { percentile: 0.75 } },
    { ...base, slug: 'op_mean_ci', operation: 'mean_confidence_interval', confidenceLevel: 0.95 },
    { ...base, slug: 'op_weighted_mean_ci', operation: 'weighted_mean_confidence_interval', weightField: 'survey_weight', confidenceLevel: 0.95 },
    { ...base, slug: 'op_prop_ci', operation: 'proportion_confidence_interval', confidenceLevel: 0.95, parameters: filter },
    { ...base, slug: 'op_weighted_prop_ci', operation: 'weighted_proportion_confidence_interval', weightField: 'survey_weight', confidenceLevel: 0.95, parameters: filter },
  ];
  const localCatalog = validateCatalog(catalog({ metrics }), profile);
  const fields = new Map(localCatalog.fields.map((field) => [field.slug, field]));

  for (const metric of localCatalog.metrics) {
    assert.doesNotThrow(() => compileMeasures(metric, fields));
  }
});

test('the same governed slug can be compiled independently at another assignment grain', () => {
  const localCatalog = catalog({
    fields: [
      ...catalog().fields,
      {
        slug: 'score',
        label: 'Topic score',
        semanticView: 'survey_topics',
        dataType: 'number',
        sourceKind: 'raw_json',
        sourceKey: 'Score',
        visibility: 'viewer',
      },
    ],
    metrics: [],
  });
  const validated = validateCatalog(localCatalog, profile);
  const assignmentCore = [
    '    measures:',
    '      # __LOCAL_MEASURES__',
    '    dimensions:',
    '      # __LOCAL_DIMENSIONS__',
  ].join('\n');

  assert.match(
    injectCatalog(assignmentCore, validated, 'survey_topics'),
    /name: score/,
  );
});

test('published chart rollups preserve their exact dimensions and month partitions', () => {
  const rollup = {
    name: 'chart_42_score_p90',
    semanticView: 'survey_responses',
    measures: ['score_p90'],
    dimensions: ['store_key', 'region'],
    timeDimension: 'reported_at',
    granularity: 'day',
    partitionGranularity: 'month',
    nonAdditive: true,
  };
  const compiled = compileRollup(rollup);

  assert.match(compiled, /- score_p90/);
  assert.match(compiled, /- store_key/);
  assert.match(compiled, /- region/);
  assert.match(compiled, /partition_granularity: month/);
  assert.doesNotMatch(compiled, /rollup_join|number_agg/);
});

test('responding store count is accepted as a fixed response-view measure', () => {
  const withRespondingStores = catalog({
    rollups: [{
      name: 'chart_43_responding_stores',
      semanticView: 'survey_responses',
      measures: ['responding_store_count'],
      dimensions: ['region'],
      timeDimension: null,
      granularity: null,
      partitionGranularity: null,
      nonAdditive: true,
    }],
  });

  assert.equal(validateCatalog(withRespondingStores, profile).rollups.length, 1);
});

test('pre-aggregation refresh interval is injected into core and chart rollups', () => {
  const core = [
    '    refresh_key:',
    '      every: __PRE_AGGREGATION_REFRESH_EVERY__',
    '      # __LOCAL_DIMENSIONS__',
    '      # __LOCAL_MEASURES__',
    '      # __LOCAL_PREAGGREGATIONS__',
  ].join('\n');
  const localCatalog = validateCatalog(catalog({
    rollups: [{
      name: 'chart_42_responses',
      semanticView: 'survey_responses',
      measures: ['response_count'],
      dimensions: ['store_key'],
      timeDimension: null,
      granularity: null,
      partitionGranularity: null,
      nonAdditive: false,
    }],
  }), profile);

  const compiled = injectCatalog(core, localCatalog, 'survey_responses', '5 minute');

  assert.doesNotMatch(compiled, /__PRE_AGGREGATION_REFRESH_EVERY__/);
  assert.equal((compiled.match(/every: 5 minute/g) || []).length, 2);
});

test('pre-aggregation refresh interval rejects unsafe Cube schema content', () => {
  const rollup = {
    name: 'chart_42_responses',
    semanticView: 'survey_responses',
    measures: ['response_count'],
    dimensions: ['store_key'],
    timeDimension: null,
    granularity: null,
    partitionGranularity: null,
    nonAdditive: false,
  };

  assert.throws(
    () => compileRollup(rollup, [], '15 minute\n      sql: SELECT pg_sleep(10)'),
    /Invalid pre-aggregation refresh interval/,
  );
});

test('chart rollups materialize confidence and data-quality supporting measures', () => {
  const rollup = {
    name: 'chart_42_weighted_score',
    semanticView: 'survey_responses',
    measures: ['weighted_score_ci'],
    dimensions: ['store_key'],
    timeDimension: 'reported_at',
    granularity: 'month',
    partitionGranularity: 'year',
    nonAdditive: true,
  };
  const compiled = compileRollup(rollup, [{
    slug: 'weighted_score_ci',
    operation: 'weighted_mean_confidence_interval',
  }]);

  assert.match(compiled, /weighted_score_ci__invalid_weight_count/);
  assert.match(compiled, /weighted_score_ci__weight_sum_squares/);
  assert.match(compiled, /weighted_score_ci__weighted_value_square_sum/);
});

test('untimed rollups omit partition granularity', () => {
  const compiled = compileRollup({
    name: 'chart_42_untimed',
    semanticView: 'survey_responses',
    measures: ['response_count'],
    dimensions: ['region'],
    timeDimension: null,
    granularity: null,
    partitionGranularity: null,
    nonAdditive: false,
  });

  assert.doesNotMatch(compiled, /time_dimension|granularity/);
  assert.match(compiled, /scheduled_refresh: true/);
});

test('catalog rejects a timed rollup without a Cube-supported granularity', () => {
  const invalid = catalog({
    rollups: [
      {
        name: 'chart_42_weekly',
        semanticView: 'survey_responses',
        measures: ['response_count'],
        dimensions: ['store_key'],
        timeDimension: 'reported_at',
        granularity: null,
        partitionGranularity: 'month',
        nonAdditive: false,
      },
    ],
  });

  assert.throws(() => validateCatalog(invalid, profile), /invalid granularity/);
});

test('query rewrite blocks cross-profile and viewer access while allowing refresh worker builds', async () => {
  const previousFetch = global.fetch;
  const previousEnvironment = {
    ANALYTICS_METADATA_URL: process.env.ANALYTICS_METADATA_URL,
    ANALYTICS_METADATA_SECRET: process.env.ANALYTICS_METADATA_SECRET,
    ANALYTICS_PROFILE: process.env.ANALYTICS_PROFILE,
  };
  process.env.ANALYTICS_METADATA_URL = 'http://backend/internal/analytics/catalog';
  process.env.ANALYTICS_METADATA_SECRET = 'metadata-secret';
  process.env.ANALYTICS_PROFILE = profile;
  let headers;
  global.fetch = async (_url, options) => {
    headers = options.headers;
    return new Response(JSON.stringify(catalog()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const query = { dimensions: ['survey_responses.private_note'] };

  try {
    await assert.rejects(
      enforceSecurityContext(query, { securityContext: { profile: 'other_cls', role: 'admin' } }),
      /not scoped/,
    );
    await assert.rejects(
      enforceSecurityContext(query, { securityContext: { profile, role: 'viewer' } }),
      /not visible/,
    );
    await assert.rejects(
      enforceSecurityContext({
        filters: [{ or: [{ member: 'survey_responses.private_note', operator: 'set' }] }],
      }, { securityContext: { profile, role: 'viewer' } }),
      /not visible/,
    );
    await assert.rejects(
      enforceSecurityContext({
        measures: ['survey_responses.private_note__invalid_weight_count'],
      }, { securityContext: { profile, role: 'viewer' } }),
      /not visible/,
    );
    await assert.rejects(
      enforceSecurityContext({
        order: { 'survey_responses.private_note': 'asc' },
      }, { securityContext: { profile, role: 'viewer' } }),
      /not visible/,
    );
    assert.equal(
      await enforceSecurityContext(query, { securityContext: { profile, role: 'refresh_worker' } }),
      query,
    );
    assert.equal(headers['X-Analytics-Profile'], profile);
    assert.match(headers['X-Analytics-Signature'], /^[0-9a-f]{64}$/);
  } finally {
    global.fetch = previousFetch;
    for (const [name, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test('catalog version rejects changed metadata at an unchanged version', async () => {
  const previousFetch = global.fetch;
  const previousEnvironment = {
    ANALYTICS_METADATA_URL: process.env.ANALYTICS_METADATA_URL,
    ANALYTICS_METADATA_SECRET: process.env.ANALYTICS_METADATA_SECRET,
    ANALYTICS_PROFILE: process.env.ANALYTICS_PROFILE,
  };
  process.env.ANALYTICS_METADATA_URL = 'http://backend/internal/analytics/catalog';
  process.env.ANALYTICS_METADATA_SECRET = 'metadata-secret';
  process.env.ANALYTICS_PROFILE = profile;
  let changed = false;
  global.fetch = async () => new Response(JSON.stringify(catalog({
    catalogVersion: 20,
    fields: catalog().fields.map((field) => (
      field.slug === 'score' && changed ? { ...field, label: 'Changed label' } : field
    )),
  })), { status: 200, headers: { 'Content-Type': 'application/json' } });

  try {
    assert.equal(await catalogVersion(), `${profile}:20`);
    changed = true;
    await assert.rejects(catalogVersion(), /without advancing catalogVersion/);
  } finally {
    global.fetch = previousFetch;
    for (const [name, value] of Object.entries(previousEnvironment)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
