import test from 'node:test';
import assert from 'node:assert/strict';
import {clampZoom,safeRecord,stationRecords,searchRecords,collectionPage,collectionRecords} from '../src/spatialRecords.ts';

test('physical pages contain only exact station records, six at a time',()=>{
  const items=Array.from({length:15},(_,i)=>({id:'c'+i,station:'engineering',title:'Saved patch',description:'Owned source',status:'drafted'}));
  items.push({id:'person:one',station:'demo',title:'Person',description:'Member',status:'enabled'});
  assert.deepEqual(stationRecords(items,'engineering',1).map(r=>r.id),['c6','c7','c8','c9','c10','c11']);
  assert.equal(stationRecords(items,'access').length,0);
  assert.equal(stationRecords(items,'engineering',2).length,3);
  assert.equal(safeRecord(items,'demo','c1'),null);
  assert.equal(safeRecord(items,'engineering','not-saved'),null);
  assert.equal(safeRecord(items,'engineering','c1').id,'c1');
});
test('zoom stays finite and bounded for wheel, keyboard and corrupted inputs',()=>{
  assert.equal(clampZoom(100),3.2);assert.equal(clampZoom(-100),.65);
  assert.equal(clampZoom(Infinity),1);assert.equal(clampZoom(NaN),1);assert.equal(clampZoom(1.9),1.9);
});

const saved=[
  {id:'one',station:'engineering',title:'Jinja export',description:'Review template output',status:'checks_passed',by:'Jonas',path:'src/export.py'},
  {id:'two',station:'access',title:'Atlas access',description:'Read only until Friday',status:'revoked',by:'Mina'},
];
test('collection search matches multiple words across owner, path and readable status',()=>{
  assert.deepEqual(searchRecords(saved,'JONAS passed export.py').map(i=>i.id),['one']);
  assert.deepEqual(searchRecords(saved,'  read\tFRIDAY\nmina  ').map(i=>i.id),['two']);
  assert.deepEqual(searchRecords(saved,'Ｊｉｎｊａ').map(i=>i.id),['one']);
});
test('search does not mutate, invent or retrieve records outside the supplied collection',()=>{
  const scope=saved.filter(i=>i.station==='engineering'),before=structuredClone(saved);
  assert.deepEqual(searchRecords(scope,'Atlas'),[]);
  assert.equal(searchRecords(scope,'   '),scope);
  assert.deepEqual(saved,before);
  assert.deepEqual(searchRecords([], 'anything'),[]);
});
test('search is literal, tolerates missing optional fields and requires every word',()=>{
  assert.deepEqual(searchRecords(saved,'.*'),[]);
  assert.deepEqual(searchRecords(saved,'Jonas revoked'),[]);
  assert.equal(searchRecords(saved,'revoked')[0].id,'two');
});
test('a shrinking collection or corrupt page cannot strand the user on a blank page',()=>{
  assert.equal(collectionPage(3,21),3);assert.equal(collectionPage(3,7),1);
  assert.equal(collectionPage(3,6),0);assert.equal(collectionPage(3,0),0);
  assert.equal(collectionPage(-3,21),0);assert.equal(collectionPage(Infinity,21),0);
  assert.equal(collectionPage(NaN,21),0);assert.equal(collectionPage(1.8,21),1);
  assert.deepEqual(stationRecords(saved,'engineering',NaN).map(i=>i.id),['one']);
});
test('one identity can belong to multiple teams without duplicate records or cross-section picks',()=>{
  const nodes=[
    {id:'team:a',station:'demo',kind:'team',parent:'organization',title:'Payments',description:'Team',status:'1 person'},
    {id:'team:b',station:'demo',kind:'team',parent:'organization',title:'Billing',description:'Team',status:'1 person'},
    {id:'person:lead',station:'demo',kind:'person',parents:['team:a','team:b'],title:'Lead',description:'Manager',status:'enabled'},
    {id:'code:private',station:'engineering',parent:'team:a',title:'Code',description:'Review',status:'drafted'},
  ];
  assert.deepEqual(collectionRecords(nodes,'demo').map(n=>n.id),['team:a','team:b']);
  assert.deepEqual(collectionRecords(nodes,'demo','team:a').map(n=>n.id),['person:lead']);
  assert.deepEqual(collectionRecords(nodes,'demo','team:b').map(n=>n.id),['person:lead']);
  assert.deepEqual(collectionRecords(nodes,'demo','unknown'),[]);
  assert.equal(nodes.filter(n=>n.id==='person:lead').length,1);
});
