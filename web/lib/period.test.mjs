import test from 'node:test';
import assert from 'node:assert/strict';
import { shiftDay, shiftRange, validateRange, cashflow } from './period.ts';

test('date stepping handles leap days and year boundaries', () => {
  assert.equal(shiftDay('2024-02-28',1),'2024-02-29');
  assert.equal(shiftDay('2026-12-31',1),'2027-01-01');
  assert.deepEqual(shiftRange({start:'2026-10-01',end:'2026-10-07'},1),{start:'2026-10-08',end:'2026-10-14'});
  assert.deepEqual(shiftRange({start:'2026-10-01',end:'2026-10-01'},-1),{start:'2026-09-30',end:'2026-09-30'});
  assert.equal(shiftRange({start:'2000-01-01',end:'2000-01-02'},-1),null);
});
test('date intervals reject invalid, reversed, out-of-bounds and excessive ranges', () => {
  assert.equal(validateRange({start:'2026-10-18',end:'2026-10-18'}),'');
  for(const range of [
    {start:'',end:'2026-10-18'},
    {start:'2026-02-30',end:'2026-03-01'},
    {start:'2026-10-18',end:'2026-10-17'},
    {start:'1999-12-31',end:'2000-01-01'},
    {start:'2100-12-31',end:'2101-01-01'},
    {start:'2026-01-01',end:'2037-01-01'},
  ]) assert.ok(validateRange(range),JSON.stringify(range));
});
test('daily charts include both boundary days and zero-fill missing dates', () => {
  const flow=cashflow([
    {date:'2026-10-01',income:'100.50',expense:'0'},
    {date:'2026-10-03',income:'0',expense:'25.25'},
    {date:'2026-10-04',income:'999',expense:'0'},
  ],'2026-10-01','2026-10-03');
  assert.equal(flow.monthly,false);
  assert.deepEqual(flow.points,[
    {date:'2026-10-01',income:100.5,expense:0},
    {date:'2026-10-02',income:0,expense:0},
    {date:'2026-10-03',income:0,expense:25.25},
  ]);
});
test('long charts aggregate partial months and exclude dates outside the interval', () => {
  const flow=cashflow([
    {date:'2026-01-14',income:'999',expense:'0'},
    {date:'2026-01-15',income:'100',expense:'0'},
    {date:'2026-01-31',income:'50',expense:'0'},
    {date:'2026-05-01',income:'0',expense:'25'},
    {date:'2026-05-02',income:'0',expense:'999'},
  ],'2026-01-15','2026-05-01');
  assert.equal(flow.monthly,true);
  assert.equal(flow.points.length,5);
  assert.deepEqual(flow.points[0],{date:'2026-01',income:150,expense:0});
  assert.deepEqual(flow.points[4],{date:'2026-05',income:0,expense:25});
});
