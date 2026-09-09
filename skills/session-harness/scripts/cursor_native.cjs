// Read quota through the installed CLI's native authentication and transport.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const crypto = require('node:crypto');

(async () => {
  const entry = path.join(fs.realpathSync(process.argv[2]), 'index.js');
  const source = fs.readFileSync(entry, 'utf8');
  // Reviewed 2026.09.08-6caf4ff native entries: Linux x64 and macOS arm64.
  const hashes = ['61b58f6a0b9e64970fce5f001526996a786a121f3d8836fa2e1d4b3629f3b02f',
                  'f7875cfc3bd084d5105c579f1dd21aa77561d72bc2a528cdb70219636186bc79'];
  if (!hashes.includes(crypto.createHash('sha256').update(source).digest('hex'))) throw Error('unreviewed native entry');
  const marker = 'var __webpack_exports__=__webpack_require__("./src/main.tsx")';
  if (source.split(marker).length !== 2) throw Error('unsupported native entry');
  const module = new Module(entry);
  module.filename = entry;
  module.paths = Module._nodeModulePaths(path.dirname(entry));
  module._compile(source.replace(marker, 'module.exports=__webpack_require__'), entry);
  const native = module.exports;
  const credentials = native('../cli-credentials/dist/index.js').jo({domain:'cursor', store:'default'});
  if (await credentials.getApiKey()) throw Error('API authentication is unsupported');
  if (await credentials.getBedrockCredentials()) throw Error('Bedrock authentication is unsupported');
  const client = native('./src/dashboard-client.ts').m({credentialManager:{getAccessToken:()=>credentials.getAccessToken(), getApiKey:async()=>undefined, setAuthentication:async()=>{throw Error('refresh disabled');}}, endpoint:'https://api2.cursor.sh'});
  const options = {timeoutMs:10000};
  const observedAt = Date.now() / 1000;
  const [account, plan, usage, hardLimit, limits, grants] = await Promise.all([
    client.getMe({}, options), client.getPlanInfo({}, options),
    client.getCurrentPeriodUsage({}, options), client.getHardLimit({}, options),
    client.getUsageLimitStatusAndActiveGrants({}, options), client.getCreditGrantsBalance({}, options)
  ]);
  if (!account.userId || account.teamId || account.isEnterpriseUser) throw Error('personal account required');
  const result = {
    observed_at: observedAt,
    account_fingerprint: crypto.createHash('sha256').update(`cursor:${account.userId}`).digest('hex'),
    plan: {planName:plan.toJson().planInfo.planName},
    usage: usage.toJson(), hard_limit: hardLimit.toJson(),
    limits: limits.toJson(), grants: grants.toJson()
  };
  // Emit only quota fields; never return credentials, account details or messages.
  delete result.usage.bonusTooltip;
  for (const key of ['displayMessage','autoModelSelectedDisplayMessage','namedModelSelectedDisplayMessage']) delete result.usage[key];
  if (result.usage.planUsage) delete result.usage.planUsage.bonusTooltip;
  const keys = ['billingCycleStart','billingCycleEnd','planUsage','spendLimitUsage','displayThreshold','autoBucketModels'];
  if (Object.keys(result.usage).some(key=>!keys.includes(key))) throw Error('unknown usage class');
  result.usage = Object.fromEntries(keys.slice(0,4).map(key=>[key,result.usage[key]]));
  result.hard_limit = {noUsageBasedAllowed:result.hard_limit.noUsageBasedAllowed};
  result.limits = Object.keys(result.limits).some(key=>key!=='usageLimitPolicyStatus') ? {unsupported:true} : {usageLimitPolicyStatus:{}};
  result.grants = Object.keys(result.grants).length ? {present:true} : {};
  process.stdout.write(JSON.stringify(result));
})().catch(() => {process.stderr.write('Cursor native quota contract unavailable\n'); process.exitCode = 1;});
