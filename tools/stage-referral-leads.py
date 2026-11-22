"""Stage a bounded JSONL scrape for review in Databricks."""
import argparse
import json
from pathlib import Path
import subprocess
import time

TABLE = 'workspace.referral_verification.demo_scraped_source_leads'
SCHEMA = ('facility_id STRING, service STRING, source_type STRING, publisher STRING, '
          'url STRING, checked STRING, name STRING, excerpt STRING, rationale STRING, review_status STRING')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--profile', default='virtue-datathon')
    parser.add_argument('--warehouse', default='745fb903b957561a')
    parser.add_argument('--cli', default='databricks')
    args = parser.parse_args()

    def api(method, path, body=None):
        command = [args.cli, 'api', method, path, '-p', args.profile, '-o', 'json']
        if body is not None:
            command.extend(['--json', json.dumps(body)])
        return json.loads(subprocess.check_output(command, text=True))

    def execute(sql, params=()):
        path = '/api/2.0/sql/statements'
        body = {'warehouse_id': args.warehouse, 'statement': sql, 'wait_timeout': '10s',
                'parameters': [{'name': name, 'value': value, 'type': 'STRING'} for name, value in params]}
        result = api('post', path, body)
        for _ in range(40):
            if result['status']['state'] not in ('PENDING', 'RUNNING'):
                break
            time.sleep(1)
            result = api('get', path + '/' + result['statement_id'])
        if result['status']['state'] != 'SUCCEEDED':
            raise RuntimeError(result['status'])

    rows = [json.loads(line) for line in args.input.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not 0 < len(rows) <= 100:
        parser.error('Provide between 1 and 100 scraped records per run')
    required = ('source_type', 'publisher', 'url', 'checked', 'excerpt', 'rationale')
    if any(any(not row.get(key) for key in required) or row.get('review_status') != 'lead' for row in rows):
        parser.error('Each row must be a complete unreviewed lead')
    execute(f'CREATE TABLE IF NOT EXISTS {TABLE} (lead_id STRING, {SCHEMA}) USING DELTA')
    execute(f"""MERGE INTO {TABLE} target USING (
      SELECT DISTINCT sha2(to_json(lead),256) lead_id, lead.*
      FROM (SELECT explode(from_json(:records, 'ARRAY<STRUCT<{SCHEMA.replace(" STRING", ": STRING")}>>')) lead)
    ) source ON target.lead_id = source.lead_id
    WHEN NOT MATCHED THEN INSERT *""", [('records', json.dumps(rows, ensure_ascii=False))])
    print(f'{len(rows)} scraped leads processed in {TABLE}. Review before publishing as facility evidence.')


if __name__ == '__main__':
    main()
