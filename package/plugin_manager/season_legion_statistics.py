"""Selected-legion statistics, resumable report reads and explicit coverage."""
from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import logging
import math
import time
from .native_diagnostics import checkpoint

LOG=logging.getLogger('plugin_manager')

# SeasonConstantCfg.ScorePer, verified against the extracted game config and
# retained leaderboard examples. New rank snapshots carry the live config.
DEFAULT_SCORE_RULE=[10,1,1]


def apply_score(row,rule=None):
    """Preserve server scores; derive missing scores only from complete counts."""
    before=(row.get('score'),row.get('scoreSource'))
    if row.get('score') is not None and row.get('scoreSource')!='规则计算':
        row['scoreSource']='服务端结算' if row.get('statisticsSource')=='服务端结算' else row.get('scoreSource') or '服务端排名'
    else:
        rule=DEFAULT_SCORE_RULE if rule is None else rule
        counts=[row.get(key) for key in ('killRoleNum','killGuardNum','dieNum')]
        valid=(isinstance(rule,(list,tuple)) and len(rule)==3
            and all(isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n) and n>=0 for n in rule)
            and row.get('statisticsComplete')
            and all(isinstance(n,int) and not isinstance(n,bool) and n>=0 for n in counts))
        row['score']=sum(n*factor for n,factor in zip(counts,rule)) if valid else None
        row['scoreSource']='规则计算' if valid else '统计不完整'
    return before!=(row.get('score'),row.get('scoreSource'))


def report_participants(report):
    """Raw role IDs remain usable when the service omits a role preview."""
    for info_key, preview_key in (('roleInfo','rolePreview'),('tarRoleInfo','tarRolePreview')):
        preview=report.get(preview_key) or {}
        info=report.get(info_key) or {}
        pid=str(info.get('roleId') or preview.get('id') or '')
        if pid.isdigit() and int(pid)>=100000:
            yield dict(preview,id=int(pid),membershipSource='本场战报')


async def scan_battlefield(feature,args,session,generation):
    """Scan ranked legions first, then close the accessible report graph."""
    panel=feature.panel;account=panel.account;bucket=panel.cache[account]
    war=str(args['warId']);prefix=war+':'
    ranks=bucket['ranks'][war]
    groups=bucket.setdefault('legion_statistics',{})
    scans=bucket.setdefault('battlefield_scans',{})
    previous=scans.get(war,{})
    members={str(r['id']):dict(r) for r in previous.get('rows',[])}
    failures={};processed=set();round_no=0
    legion_names={str(r['id']):r.get('name','') for r in ranks.get('legions',[])}

    def add(row,legion=None):
        pid=str(row.get('id') or '')
        if not pid.isdigit() or int(pid)<100000:return
        target=members.setdefault(pid,{'id':int(pid)})
        # Enrich missing identity fields without discarding completed statistics.
        for key,value in row.items():
            if value is not None and (key not in target or target[key] in (None,'')):
                target[key]=value
        if legion and not target.get('legionId'):target['legionId']=legion
        if target.get('legionId'):
            target['legionName']=legion_names.get(str(target['legionId']),target.get('legionName',''))
        else:target['legionName']='阴司未知'

    def import_groups():
        for key,snapshot in groups.items():
            if key.startswith(prefix):
                for row in snapshot.get('rows',[]):
                    add(row,snapshot.get('legionId'))
                    members[str(row['id'])].update(row)
        for row in ranks.get('roles',[]):
            target=members.get(str(row['id']))
            if target and row.get('score') is not None and (target.get('score') is None or target.get('scoreSource')=='规则计算'):
                target.update(score=row['score'],scoreSource='服务端排名')

    def discover():
        for key,snapshot in bucket['reports'].items():
            if key.startswith(prefix):
                for report in snapshot.get('rows',[]):
                    for row in report_participants(report):add(row)

    def save(phase,complete=False):
        for row in members.values():apply_score(row,ranks.get('scoreRule'))
        scans[war]=dict(warId=war,rows=list(members.values()),round=round_no,
            processed=len(processed),phase=phase,complete=complete,failures=dict(failures),
            fetchedAt=datetime.now(timezone.utc).isoformat())
        panel.save()

    for row in ranks.get('roles',[]):
        add(row)
        if row.get('score') is not None:
            members[str(row['id'])].update(score=row['score'],scoreSource='服务端排名')
    import_groups()
    for index,legion in enumerate(ranks.get('legions',[]),1):
        if not feature.current(session,generation):return
        panel.message.setText(f"第一轮：阴司 {index}/{len(legion_names)} · {legion.get('name',legion['id'])}")
        checkpoint(f"season-scan legion war={war} legion={legion['id']} index={index}")
        try:
            await load_legion_statistics(feature,dict(args,legionId=legion['id'],
                legionName=legion.get('name',''),memberNum=legion.get('memberNum'),firstPassOnly=True),session,generation)
        except Exception as exc:
            if not feature.current(session,generation):return
            failures['legion:'+str(legion['id'])]=str(exc)
            LOG.exception('全场扫描阴司失败：%s',legion['id'])
        if not feature.current(session,generation):return
        group=groups.get(prefix+str(legion['id']),{})
        if group.get('note'):failures['legion:'+str(legion['id'])]=group['note']
        import_groups();save('阴司扫描')
        await asyncio.sleep(0)

    # Own-legion settlement and complete legion snapshots may have skipped
    # reports. Every known player still enters this frontier exactly once/run.
    discover()
    while feature.current(session,generation):
        frontier=[pid for pid in members if pid not in processed]
        if not frontier:break
        round_no+=1
        for index,pid in enumerate(frontier,1):
            if not feature.current(session,generation):return
            row=members[pid]
            panel.message.setText(f'战报扩展第 {round_no} 轮：{index}/{len(frontier)} · 已发现 {len(members)} 人 · 失败 {len(failures)} 项')
            checkpoint(f'season-scan player war={war} round={round_no} player={pid}')
            try:
                reports=await load_reports(feature,dict(args,roleId=int(pid),reportFilter='players'),session,generation,account)
                if reports is None:return
                if not row.get('statisticsComplete'):
                    player_rows=[r for r in reports['rows'] if len(list(report_participants(r)))==2]
                    counts=report_statistics(player_rows,pid);unresolved=counts.pop('unresolved')
                    counts.pop('killGuardNum')
                    row.update(counts,statisticsComplete=not unresolved,statisticsSource='玩家战报统计'+('（含未结算记录）' if unresolved else ''))
                if row.get('killGuardNum') is None:
                    full=bucket['reports'].get(prefix+pid,{})
                    if full.get('complete'):
                        count=report_statistics(full['rows'],pid)['killGuardNum']
                    else:
                        guard=await feature.transport.season_insight('guard_count',dict(args,roleId=int(pid)))
                        if not feature.current(session,generation):return
                        count=guard.get('total')
                        if not isinstance(count,int) or isinstance(count,bool) or count<0:raise RuntimeError('攻城战报总次数无效')
                    row.update(killGuardNum=count,guardSource='完整战报缓存' if full.get('complete') else '守卫战报首页 total')
                if not row.get('statisticsComplete'):failures[pid]='战报包含未结算记录'
            except Exception as exc:
                if not feature.current(session,generation):return
                failures[pid]=str(exc)
                LOG.exception('全场扫描玩家失败：战场=%s 玩家=%s',war,pid)
            processed.add(pid)
            # Import even partial pages after a failure: their participants are
            # valid leads. Failed IDs are retried on the next click, never spun.
            for key in (prefix+pid,prefix+pid+':players'):
                for report in bucket['reports'].get(key,{}).get('rows',[]):
                    for participant in report_participants(report):add(participant)
            legion_id=row.get('legionId')
            apply_score(row,ranks.get('scoreRule'))
            if legion_id:
                key=prefix+str(legion_id)
                group=groups.setdefault(key,dict(args,legionId=legion_id,
                    legionName=legion_names.get(str(legion_id),row.get('legionName','')),rows=[]))
                rows={str(r['id']):r for r in group['rows']};rows[pid]=dict(row)
                group.update(rows=list(rows.values()),complete=not group.get('note') and all(r.get('statisticsComplete') and r.get('killGuardNum') is not None for r in rows.values()),
                    fetchedAt=datetime.now(timezone.utc).isoformat())
            save('战报扩展')
            await asyncio.sleep(0)
    if not feature.current(session,generation):return
    save('已结束',complete=not failures)
    panel.show_all_roles()
    panel.message.setText(f'全场扫描结束：战报扩展 {round_no} 轮 · 已发现 {len(members)} 人 · 失败 {len(failures)} 项。'
        '已读战报中没有新的玩家；无战报或不可访问的玩家仍可能遗漏。结果已缓存，再次拉取可补读失败项。'
        + ('\n失败项：'+'；'.join(f'{key}：{value}' for key,value in list(failures.items())[:5]) if failures else ''))
    LOG.info('全场扫描结束：战场=%s 轮次=%s 玩家=%s 失败=%s',war,round_no,len(members),failures)


def complete_statistics(snapshot):
    return snapshot.get('complete') and all(r.get('killGuardNum') is not None for r in snapshot.get('rows',[]))


def report_key(row):
    return ('battle', str(row['battleId'])) if row.get('battleId') else (
        'record', row.get('time'), (row.get('roleInfo') or {}).get('roleId'),
        (row.get('tarRoleInfo') or {}).get('roleId'), row.get('buildingId'))


def report_statistics(reports, role_id):
    role_id = str(role_id)
    kills = guards = deaths = unresolved = 0
    seen = set()
    for row in reports:
        key = report_key(row)
        if key in seen:
            continue
        seen.add(key)
        attacker = str((row.get('roleInfo') or {}).get('roleId', ''))
        defender = str((row.get('tarRoleInfo') or {}).get('roleId', ''))
        winner = str(row.get('winRoleId') or '')
        if role_id not in (attacker, defender) or not winner or winner not in (attacker, defender):
            unresolved += 1
            continue
        other = defender if attacker == role_id else attacker
        if winner != role_id:
            deaths += 1
        elif other.isdigit() and 0 < int(other) < 100000:
            guards += 1
        elif other.isdigit() and int(other) >= 100000:
            kills += 1
        else:
            unresolved += 1
    return dict(killRoleNum=kills, killGuardNum=guards, dieNum=deaths, unresolved=unresolved)


async def load_reports(feature, args, session, generation, account, *, force=False):
    """Persist every page, including the resume offset; never label partial data complete."""
    panel = feature.panel
    cache = panel.cache[account]['reports']
    base_key = str(args['warId']) + ':' + str(args['roleId'])
    players_only=args.get('reportFilter')=='players'
    key=base_key+(':players' if players_only else '')
    # A complete historical all-report snapshot already covers player battles.
    # Never reuse its pagination cursor for a filtered server response.
    if players_only and not force and cache.get(base_key,{}).get('complete'):
        return cache[base_key]
    saved = cache.get(key, {}) if not force else {}
    if saved.get('complete'):
        return saved
    # Legacy snapshots lack a trustworthy page cursor: re-read them once.
    rows = list(saved.get('rows', [])) if 'nextStart' in saved else []
    start = saved.get('nextStart', 0)
    seen = {report_key(r) for r in rows}
    while feature.current(session, generation):
        checkpoint(f"season-report-request begin war={args['warId']} player={args['roleId']} start={start}")
        page = await feature.transport.season_insight('reports', dict(args, start=start))
        checkpoint(f"season-report-request done player={args['roleId']} count={len(page.get('rows',[]))} total={page.get('total')}")
        if not feature.current(session, generation):
            return None
        batch = page['rows']
        new = [r for r in batch if report_key(r) not in seen]
        if batch and not new:
            raise RuntimeError('战报分页重复，已保留进度，请手动刷新本阴司重试')
        for row in new:
            identity = report_key(row)
            if identity not in seen:
                seen.add(identity)
                rows.append(row)
        start += len(batch)
        total = page.get('total', 0)
        if not batch and total > start:
            raise RuntimeError('战报分页提前结束，统计尚未完整')
        complete = start >= total if total > 0 else len(batch) < 15
        saved = dict(args, rows=list(rows), nextStart=start, total=total, complete=complete,
                     fetchedAt=datetime.now(timezone.utc).isoformat())
        panel.save_report(account,key,saved)
        LOG.info('血月战报进度：战场=%s 玩家=%s 已保存=%s 总数=%s 完整=%s',args['warId'],args['roleId'],len(rows),total,complete)
        await asyncio.sleep(0)
        if complete:
            return saved
    return None


async def load_legion_statistics(feature, args, session, generation):
    panel = feature.panel
    account = panel.account
    bucket = panel.cache[account]
    groups = bucket.setdefault('legion_statistics', {})
    key = str(args['warId']) + ':' + str(args['legionId'])
    force = bool(args.get('force'))
    previous = groups.get(key, {})
    score_rule=bucket['ranks'].get(str(args['warId']),{}).get('scoreRule')
    ranked={str(r['id']):r for r in bucket['ranks'].get(str(args['warId']),{}).get('roles',[])}
    for row in previous.get('rows',[]):
        server=ranked.get(str(row['id']),{})
        if server.get('score') is not None and (row.get('score') is None or row.get('scoreSource')=='规则计算'):
            row.update(score=server['score'],scoreSource='服务端排名')
        apply_score(row,score_rule)
    if complete_statistics(previous) and not force:
        panel.save()
        panel.show_legion_statistics(previous)
        return
    target = str(args['legionId'])
    members = {str(r['id']): dict(r) for r in previous.get('rows', [])}
    ranks = bucket['ranks'].get(str(args['warId']), {})
    for row in ranks.get('roles', []):
        if str(row.get('legionId')) == target:
            members.setdefault(str(row['id']), {}).update(row, membershipSource='本场排名')
            if row.get('score') is not None:members[str(row['id'])]['scoreSource']='服务端排名'
    expected = args.get('memberNum')
    note = ''
    try:
        roster = await feature.transport.season_insight('legion_roster', args)
        if not feature.current(session, generation):
            return
        expected = roster.get('memberNum', expected)
        for row in roster['members']:
            members.setdefault(str(row['id']), dict(row))
    except Exception as exc:
        note = '当前阴司预览不可用：' + str(exc)
    direct = {}
    if target == account.split(':')[-1]:
        try:
            stats = await feature.transport.season_insight('statistics', args)
            if not feature.current(session, generation):
                return
            direct = {str(r['id']): r for r in stats['rows']}
            for pid, row in direct.items():
                members.setdefault(pid, {}).update(row, membershipSource='本场结算')
        except Exception as exc:
            note += '；本阴司结算不可用：' + str(exc)

    def discover():
        if args.get('firstPassOnly'):return
        for cache_key, snapshot in bucket['reports'].items():
            if not cache_key.startswith(str(args['warId']) + ':'):
                continue
            for report in snapshot.get('rows', []):
                for preview in (report.get('rolePreview'), report.get('tarRolePreview')):
                    if preview and str(preview.get('legionId')) == target and int(preview.get('id') or 0) >= 100000:
                        members.setdefault(str(preview['id']), dict(preview, membershipSource='本场战报'))
    discover()
    processed = set()
    failures = []
    snapshot = None
    next_render = 0
    LOG.info('开始阴司统计：战场=%s 阴司=%s 已知成员=%s 强制刷新=%s',args['warId'],target,len(members),force)
    # Reports can reveal further members outside the global top 100.
    while feature.current(session, generation):
        todo = [pid for pid in members if pid not in processed]
        if not todo:
            break
        pid = todo[0]
        processed.add(pid)
        row = members[pid]
        if row.get('statisticsComplete') and row.get('killGuardNum') is not None and not force:
            # The per-member snapshot is already durable; resuming need not
            # re-render and rewrite it for every completed member.
            await asyncio.sleep(0)
            continue
        LOG.info('阴司统计成员开始：战场=%s 阴司=%s 玩家=%s 进度=%s/%s',args['warId'],target,pid,len(processed),len(members))
        checkpoint(f"season-member begin war={args['warId']} legion={target} player={pid} progress={len(processed)}/{len(members)}")
        panel.message.setText(f"正在统计 {args.get('legionName', target)}：{len(processed)}/{len(members)} · {row.get('name', pid)}")
        if pid in direct:
            row.update({k: direct[pid].get(k) for k in ('killRoleNum', 'killGuardNum', 'dieNum', 'score')},
                       statisticsSource='服务端结算', statisticsComplete=True,scoreSource='服务端结算')
        elif not (row.get('statisticsComplete') and not force):
            try:
                reports = await load_reports(feature, dict(args, roleId=int(pid),reportFilter='players'), session, generation, account, force=force)
                if reports is None:
                    return
                player_rows=[r for r in reports['rows'] if
                    all(int((r.get(k) or {}).get('roleId') or 0)>=100000 for k in ('roleInfo','tarRoleInfo'))]
                counts = report_statistics(player_rows, pid)
                unresolved = counts.pop('unresolved')
                # Guard totals are not a kill counter. Preserve an existing
                # complete all-report count, otherwise leave the field unknown.
                full=bucket['reports'].get(str(args['warId'])+':'+pid,{})
                counts['killGuardNum']=report_statistics(full['rows'],pid)['killGuardNum'] if full.get('complete') else row.get('killGuardNum')
                row.update(counts, statisticsSource='玩家战报统计' + ('（含未结算记录）' if unresolved else ''),
                           guardSource='完整战报缓存' if full.get('complete') else '既有统计' if counts['killGuardNum'] is not None else '未获取',
                           reportScope='players',
                           statisticsComplete=not unresolved)
            except Exception as exc:
                if not feature.current(session, generation):
                    return
                row.update(killRoleNum=None, killGuardNum=None, dieNum=None,
                           statisticsSource='读取失败：' + str(exc), statisticsComplete=False)
                failures.append(pid)
        if pid not in direct and (row.get('killGuardNum') is None or force):
            try:
                checkpoint(f"season-guard-count begin war={args['warId']} player={pid}")
                guard=await feature.transport.season_insight('guard_count',dict(args,roleId=int(pid)))
                if not feature.current(session,generation):return
                count=guard.get('total')
                if not isinstance(count,int) or isinstance(count,bool) or count<0:
                    raise RuntimeError('攻城战报总次数无效')
                row.update(killGuardNum=count,guardSource='守卫战报首页 total')
                checkpoint(f'season-guard-count done player={pid} total={count}')
            except Exception as exc:
                if not feature.current(session,generation):return
                row['killGuardNum']=None
                row['guardSource']='次数读取失败：'+str(exc)
                failures.append(pid)
        apply_score(row,score_rule)
        discover()
        snapshot = dict(args, rows=list(members.values()), memberNum=expected,
                        fetchedAt=datetime.now(timezone.utc).isoformat(), complete=False, note=note)
        groups[key] = snapshot
        panel.save()
        LOG.info('阴司统计成员已保存：玩家=%s 完整=%s',pid,row.get('statisticsComplete'))
        checkpoint(f"season-member saved player={pid} complete={row.get('statisticsComplete')}")
        # Keep incremental persistence, but coalesce table replacement. Yield so
        # cached members cannot monopolize Qt's event loop during a resume.
        if time.monotonic() >= next_render:
            panel.show_legion_statistics(snapshot)
            next_render=time.monotonic()+1
        await asyncio.sleep(0)
    if not feature.current(session, generation):
        return
    snapshot = dict(args, rows=list(members.values()), memberNum=expected,
                    fetchedAt=datetime.now(timezone.utc).isoformat(),
                    complete=not failures and not note and all(r.get('statisticsComplete') and r.get('killGuardNum') is not None for r in members.values()), note=note)
    groups[key] = snapshot
    panel.save()
    panel.show_legion_statistics(snapshot)
    LOG.info('阴司统计完成：战场=%s 阴司=%s 成员=%s 完整=%s',args['warId'],target,len(members),snapshot['complete'])
