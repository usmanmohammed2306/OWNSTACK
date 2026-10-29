import {test} from 'node:test';
import assert from 'node:assert/strict';
import {placeLabels,overlaps,tooltipPosition} from '../src/spatialLayout.ts';

for (const [width,height] of [[320,360],[390,400],[646,440],[760,540],[1280,650]]) {
  test(`crowded navigation remains separated and on-screen at ${width}x${height}`,()=>{
    const labels=Array.from({length:5},(_,i)=>({id:String(i),x:width/2,y:height/2,width:128,height:44}));
    const placed=Object.values(placeLabels(labels,width,height));
    assert.ok(placed.every(Boolean));
    for (const [index,rect] of placed.entries()) {
      assert.ok(rect.x>=10 && rect.y>=10 && rect.x+rect.width<=width-10 && rect.y+rect.height<=height-10);
      for (const other of placed.slice(index+1)) assert.equal(overlaps(rect,other,10),false);
    }
  });
}
test('offscreen anchors clamp inside the stage and placement is deterministic',()=>{
  const input=[{id:'left',x:-100,y:-200,width:100,height:44},{id:'right',x:5000,y:5000,width:100,height:44}];
  assert.deepEqual(placeLabels(input,320,280),placeLabels(input,320,280));
  assert.equal(placeLabels(input,320,280).left.x,10);
  assert.equal(placeLabels(input,320,280).right.x,210);
});
test('impossible or invalid targets are never placed over other controls',()=>{
  assert.equal(placeLabels([{id:'too-wide',x:0,y:0,width:300,height:44}],100,100)['too-wide'],null);
  assert.equal(placeLabels([{id:'bad',x:NaN,y:0,width:40,height:44}],100,100).bad,null);
  assert.deepEqual(placeLabels([],Infinity,100),{});
});
test('tooltips stay in the canvas beside a reserved inspector and above the dock',()=>{
  const bounds={x:24,y:96,width:480,height:450};
  for (const [x,y] of [[0,0],[5000,5000],[240,400]]) {
    const card=tooltipPosition(x,y,bounds);
    assert.ok(card.x>=bounds.x+12 && card.y>=bounds.y+12);
    assert.ok(card.x+card.width<=bounds.x+bounds.width-12);
    assert.ok(card.y+card.height<=bounds.y+bounds.height-12);
  }
});
test('callouts cannot obscure the projected interactive model',()=>{
  const obstacle={x:220,y:40,width:360,height:300};
  const labels=Array.from({length:5},(_,i)=>({id:String(i),x:400,y:190,width:140,height:44}));
  const result=Object.values(placeLabels(labels,800,400,10,[obstacle]));
  assert.ok(result.every(Boolean));
  for(const rect of result)assert.equal(overlaps(rect,obstacle,10),false);
});
test('an occupied stage hides an unplaceable label rather than covering its model',()=>{
  assert.equal(placeLabels([{id:'room',x:150,y:100,width:100,height:44}],300,200,10,
    [{x:0,y:0,width:300,height:200}]).room,null);
});
