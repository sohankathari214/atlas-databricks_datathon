CREATE OR REPLACE FUNCTION workspace.referral_verification.referral_service_catalog()
RETURNS TABLE (payload STRING)
COMMENT 'Supported referral intents and interpretation terms for free-text intake. Facility ranking uses search_referrals.'
RETURN
WITH catalog AS (
  SELECT * FROM VALUES
    ('mri','MRI','A requested magnetic resonance scan. CT, X-ray and ultrasound are separate services.',array('MRI','MRI scan','magnetic resonance imaging')),
    ('dialysis','Dialysis','A requested dialysis treatment or follow-up appointment. Kidney disease alone does not imply dialysis.',array('dialysis','hemodialysis','haemodialysis','peritoneal dialysis','dialysis treatment')),
    ('c_section','Emergency C-section','An explicitly requested emergency cesarean section or emergency obstetric surgical referral. Routine delivery is narrower.',array('emergency C-section','emergency cesarean','emergency caesarean','emergency caesarean section','emergency obstetric surgery','emergency obstetric care')),
    ('nicu','NICU','A requested neonatal intensive care bed or neonatal intensive care transfer.',array('NICU','neonatal intensive care','neonatal ICU')),
    ('cardiac_surgery','Cardiac surgery','A requested heart operation, such as coronary bypass or heart valve surgery. General cardiology or chest pain is insufficient.',array('cardiac surgery','heart surgery','heart operation','CABG','coronary bypass','heart bypass','heart bypass surgery','heart valve surgery')),
    ('burn_care','Burn care','An explicit need for a burn unit, burn center, or specialized treatment for a burn injury.',array('burn care','burn unit','burn center','burn centre','burn treatment')),
    ('trauma_care','Trauma care','An explicit request for a trauma service, trauma center, or major-injury transfer. An accident mention alone does not determine care.',array('trauma care','trauma center','trauma centre','trauma unit','major injury transfer')),
    ('emergency_care','Emergency department','Immediate emergency assessment for potentially time-critical symptoms such as acute chest pain, possible stroke, severe breathing problems or major bleeding.',array('emergency department','emergency room','emergency medicine','accident and emergency','24-hour emergency')),
    ('primary_care','General outpatient assessment','Initial assessment for symptoms without a clear specialist or procedure need. Use for non-emergency concerns or unsupported non-emergency specialties. No implied procedure.',array('general medicine','general practice','family medicine','outpatient department','general physician','primary care'))
  AS catalog(id,label,scope,keywords)
), supported AS (
  SELECT DISTINCT service FROM workspace.referral_verification.service_alias_config
)
SELECT to_json(sort_array(collect_list(named_struct('id',id,'label',label,'scope',scope,'keywords',keywords)))) payload
FROM catalog LEFT JOIN supported ON id=service
WHERE service IS NOT NULL OR id IN ('emergency_care','primary_care')
