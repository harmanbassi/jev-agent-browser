import test from 'node:test';
import assert from 'node:assert/strict';
import { observation, register, snapshotHash, MASK } from './index.js';

function fixture() {
  const state={url:'https://example.test/',marker:['m'],actions:[],w:1120,h:780};
  const calls=[];
  let count=0;
  const page={evaluate:async()=> ++count === 2 ? {url:state.url,actions:[],text:'safe'} : state,
    locator:s=>s, screenshot:async options=>{calls.push(options);return Buffer.from('PNG')}};
  const tab={page}, session={tabGroups:new Map([['g',new Map([['t',tab]])]])};
  const ctx={sessions:new Map([['u',session]]),normalizeUserId:u=>u,log:()=>{},auth:()=>()=>{}};
  const body={userId:'u',expectedUrl:state.url,snapshotHash};
  const run=(value=body)=>new Promise(resolve=>{
    const res={code:200,status(code){this.code=code;return this},set(){return this},json(data){resolve({code:this.code,data})}};
    observation(ctx)({body:value,params:{tabId:'t'}},res);
  });
  return {state,page,calls,ctx,body,run};
}

test('capture masks in the browser, never writes a file, and returns versioned safe data',async()=>{
  const f=fixture(), result=await f.run();
  assert.equal(result.code,200);
  assert.equal(result.data.masked,true);
  assert.deepEqual(f.calls[0].mask,[MASK]);
  assert.equal(f.calls[0].fullPage,false);
  assert.equal(f.calls[0].path,undefined);
  assert.equal(result.data.safe.text,'safe');
});
test('invalid version and identity are rejected before capture',async()=>{
  const f=fixture();
  assert.equal((await f.run({...f.body,snapshotHash:'wrong'})).code,400);
  assert.equal((await f.run({...f.body,userId:'other'})).code,404);
  assert.equal(f.calls.length,0);
});
test('navigation and errors release the capture lease without exposing data',async()=>{
  const f=fixture();
  assert.equal((await f.run({...f.body,expectedUrl:'https://other.test/'})).code,409);
  f.page.screenshot=async()=>{throw Error('private-page-data')};
  const result=await f.run();
  assert.equal(result.code,503);
  assert.ok(!JSON.stringify(result).includes('private-page-data'));
});
test('both routes use authentication',()=>{
  const routes=[];const f=fixture();
  register({get:(...args)=>routes.push(args),post:(...args)=>routes.push(args)},f.ctx);
  assert.equal(routes.length,2);
  assert.ok(routes.every(args=>args.length===3));
});
