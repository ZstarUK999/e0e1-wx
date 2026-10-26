"""Deterministic, read-only flag progression forecast using a captured game config.

All dates are Beijing calendar dates. Daily rows are decisions, never commands.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math

BEIJING = timezone(timedelta(hours=8))
WOOD, CLOTH, GOLD = '10080', '10079', '10003'


def bj_date(ms):
    return datetime.fromtimestamp(ms / 1000, BEIJING).date()


def amounts(items):
    if isinstance(items, dict):
        return {str(k): int(v) for k, v in items.items()}
    result = {}
    for row in items or []:
        key = str(row['item'])
        result[key] = result.get(key, 0) + int(row['num'])
    return result


def week_key(day):
    return day - timedelta(days=day.weekday())


def defaults(snapshot):
    return {
        'end': bj_date(snapshot['season']['end']).isoformat(), 'sweeps': 6,
        'stars_per_day': 3, 'target_stars': sum(len(s['rewards']) for s in snapshot['stages']),
        'include_today': False, 'wood_only': True,
        'active_tracks': list(snapshot['bp']['active']),
        'weekly_shop_wood': 0, 'gift_total': 0, 'weekly_recharge': False,
        'extra_cloth': 0, 'extra_gold': 0, 'days': {}, 'tasks': {},
    }


def forecast(snapshot, plan):
    """Return daily balances, pass rewards and actual/potential unlock dates.

    Today is an opening balance. Already claimed rewards are never received a
    second time. A fixed point resolves pass rewards -> upgrades -> task XP.
    """
    s = deepcopy(snapshot)
    p = {**defaults(s), **deepcopy(plan)}
    today = bj_date(s['asOf'])
    end = min(date.fromisoformat(p['end']), bj_date(s['season']['end']))
    if end < today:
        raise ValueError('预测截止日不能早于当前游戏日期')
    if (end - today).days > 370:
        raise ValueError('预测区间过长')
    levels = {r['level']: r for r in s['levels']}
    level = int(s['flagLevel'])
    maximum = max(levels)
    max_stars = sum(len(r['rewards']) for r in s['stages'])
    target_stars = max(sum(r['star'] for r in s['stages']), min(max_stars, int(p['target_stars'])))
    max_sweeps = int(s['freeSweeps']) + len(s['paidSweepCosts'])
    resources = amounts(s['resources'])
    initial_resources = dict(resources)
    totals = {name: {} for name in ('首通', '扫荡', '战令', '商店', '礼包', '额外材料')}
    spent = {}
    bp = s['bp']
    bp_level, bp_exp = int(bp['level']), int(bp['exp'])
    bp_levels = {r['level']: r for r in bp['levels']}
    bp_max = max(bp_levels)
    claimed = [int(n) for n in bp['claimed']]
    active = [True, *[bool(x) for x in p['active_tracks'][1:3]]]
    tasks = s['tasks']
    completed_season = {t['id'] for t in tasks if t['kind'] == 'season' and t['state'] == 2}
    earned = set()
    battles = sorted(set(bj_date(t) for t in s.get('battles', []) if bj_date(t) >= today))
    warnings = set()
    milestones = []
    rows = []
    gifts_left = max(0, int(p['gift_total']))
    exchange, gift = s.get('exchange'), s.get('gift')
    used_shop, used_gift = {}, {}
    shop_end = bj_date(s['season'].get('shopEnd') or s['season']['end'])
    if exchange:
        used_shop[week_key(today)] = int(exchange['bought'])
    if gift:
        used_gift[week_key(today)] = int(gift['bought'])
    skill_levels = {n for f in s.get('flags', []) for n in f['unlockLevel']}
    day_events, day_xp = [], 0
    today_upgraded = any(t['metric'] == 'dailyUpgrade' and t['state'] >= 1 for t in tasks if t['kind'] == 'daily')
    day_upgrades = 0
    tickets = int(s.get('tickets', max_stars))
    challenge = s.get('challenge')
    diamond_cost = 0
    exchange_cost = 0
    cash_cost = 0

    def stars():
        return sum(r['star'] for r in s['stages'])

    def receive(source, reward):
        reward = amounts(reward)
        for key, num in reward.items():
            resources[key] = resources.get(key, 0) + num
            totals[source][key] = totals[source].get(key, 0) + num

    def add_xp(value):
        nonlocal bp_level, bp_exp, day_xp
        day_xp += int(value)
        bp_exp += int(value)
        while bp_level < bp_max and bp_exp >= bp_levels[bp_level + 1]['exp']:
            bp_exp -= bp_levels[bp_level + 1]['exp']
            bp_level += 1

    def claim_pass():
        for track in range(3):
            if not active[track]:
                continue
            for n in sorted(bp_levels):
                if claimed[track] < n <= bp_level:
                    reward = amounts(bp_levels[n]['rewards'][track])
                    receive('战令', reward)
                    if reward.get(WOOD):
                        day_events.append(f'战令{n}级领取{reward[WOOD]}木头')
            claimed[track] = max(claimed[track], bp_level)

    def upgrade(limit=None):
        nonlocal level, day_upgrades
        count = 0
        while level < maximum and (limit is None or count < limit):
            if level + 1 not in levels:
                raise ValueError(f'缺少战旗{level + 1}级配置')
            cost = amounts(levels[level + 1]['cost'])
            if any(resources.get(k, 0) < v for k, v in cost.items()
                   if not p['wood_only'] or k == WOOD):
                break
            for k, num in cost.items():
                resources[k] = resources.get(k, 0) - num
                spent[k] = spent.get(k, 0) + num
            level += 1
            count += 1
            day_upgrades += 1
            if cost.get(WOOD) or level in skill_levels or level == maximum:
                milestones.append({'date': day.isoformat(), 'level': level, 'wood': cost.get(WOOD, 0)})
                day_events.append(f'战旗升至{level}级')

    def can_progress(row):
        if row['star'] >= len(row['rewards']) or bj_date(row['unlockAt']) > day:
            return False
        area_rows = [r for r in s['stages'] if r['areaId'] == row['areaId']]
        index = area_rows.index(row)
        if index and area_rows[index - 1]['star'] < 1:
            return False
        areas = list(dict.fromkeys(r['areaId'] for r in s['stages']))
        ai = areas.index(row['areaId'])
        previous = [r for r in s['stages'] if ai and r['areaId'] == areas[ai - 1]]
        return not previous or previous[-1]['star'] >= 1

    def task_xp(sweeps, allow_daily):
        for t in tasks:
            task_id, kind, metric = t['id'], t['kind'], t['metric']
            cycle = day if kind == 'daily' else week_key(day) if kind == 'weekly' else 'season'
            key = (task_id, cycle)
            if key in earned or task_id in completed_season:
                continue
            current_cycle = day == today if kind == 'daily' else week_key(day) == week_key(today)
            if kind != 'season' and current_cycle and t['state'] == 2:
                earned.add(key)
                continue
            ready = t['state'] == 1 and (kind == 'season' or current_cycle)
            progress = int(t['progress']) if current_cycle or kind == 'season' else 0
            target = t['target']
            explicit = (p.get('tasks') or {}).get(str(task_id))
            if explicit == 'skip':
                continue
            if kind != 'season' and not current_cycle:
                explicit = None
            if explicit and not ready:
                ready = day >= date.fromisoformat(explicit)
                # Do not let edited dates bypass resource and level prerequisites.
                if metric == 'stars': ready = ready and stars() >= target
                if metric == 'flagLevel': ready = ready and level >= target
            elif not ready:
                if metric == 'stars': ready = stars() >= target
                elif metric == 'flagLevel': ready = level >= target
                elif metric == 'sweeps': ready = allow_daily and progress + sweeps >= target
                elif metric == 'dailyUpgrade': ready = allow_daily and (day_upgrades > 0 or day == today and today_upgraded)
                elif metric == 'recharge':
                    charged = used_gift.get(week_key(day), 0) - (gift['bought'] if gift and current_cycle else 0)
                    ready = bool(p['weekly_recharge']) or progress + max(0, charged) * (gift or {}).get('price', 0) >= target
                elif metric == 'battles':
                    count = sum(today < b <= day or b == today and p['include_today'] for b in battles)
                    if kind == 'weekly':
                        count = sum(week_key(b) == week_key(day) and b <= day and
                                    (b > today or p['include_today']) for b in battles)
                    ready = progress + count >= target
                elif metric in ('march', 'revive', 'points', 'reviveItem'):
                    eligible = [b for b in battles if b <= day and (b > today or p['include_today'])]
                    if kind == 'weekly': eligible = [b for b in eligible if week_key(b) == week_key(day)]
                    # Perfect-play assumption: farm remaining actions/points on the next
                    # battle; free revives remain limited to five per battle date.
                    needed = math.ceil(max(0, target - progress) / 5) if metric == 'revive' else 1
                    ready = len(eligible) >= needed
                else:
                    warnings.add(f'任务未自动排期：{t["name"]}，可在任务页指定完成日')
            if ready:
                earned.add(key)
                if kind == 'season': completed_season.add(task_id)
                add_xp(t['score'])

    day = today
    # No reward can turn into a forecast day before this snapshot.
    while day <= end:
        day_events, day_xp, day_upgrades = [], 0, 0
        before = {name: totals[name].get(WOOD, 0) for name in totals}
        override = (p.get('days') or {}).get(day.isoformat(), {})
        allow_daily = day > today or bool(p['include_today'])
        if day > today and challenge:
            tickets = min(challenge[2], tickets + challenge[1])
        sweeps = max(0, min(max_sweeps, int(override.get('sweeps', p['sweeps'])))) if allow_daily else 0
        if day == today:
            sweeps = max(0, sweeps - int(s['todaySweeps']))
        new_stars = max(0, int(override.get('stars', p['stars_per_day']))) if allow_daily else 0
        desired = min(target_stars, stars() + min(new_stars, tickets))
        if min(new_stars, max(0, target_stars - stars())) > tickets:
            warnings.add('部分日期的推星计划超过现有探渊券与每日补充量，已按可用探渊券限制')
        while stars() < desired:
            options = [r for r in s['stages'] if can_progress(r)]
            if not options:
                break
            # Perfect clears prioritize an available higher difficulty, which
            # yields more early breakthrough material per challenge ticket.
            row = min(options, key=lambda r: (-r['star'], r['unlockAt'], r['sort']))
            receive('首通', row['rewards'][row['star']])
            row['star'] += 1
            tickets -= 1
        sweep = max((r for r in s['sweeps'] if r['stars'] <= stars()), key=lambda r: r['stars'])
        receive('扫荡', {k: v * sweeps for k, v in amounts(sweep['rewards']).items()})
        # Today's first paid sweep may already have been consumed.
        start_sweep = int(s['todaySweeps']) if day == today else 0
        for n in range(start_sweep, start_sweep + sweeps):
            if n >= s['freeSweeps']:
                diamond_cost += s['paidSweepCosts'][n - s['freeSweeps']]
        if allow_daily:
            receive('额外材料', {CLOTH: int(p['extra_cloth']), GOLD: int(p['extra_gold'])})
        week = week_key(day)
        shop_count = gift_count = 0
        for kind, goods in (('商店', exchange), ('礼包', gift)):
            if not goods or day > shop_end or bj_date(goods['unlockAt']) > day:
                continue
            if goods['refresh'] != 2:
                warnings.add(f'{goods["name"]}刷新周期不是周，未自动安排')
                continue
            used = used_shop if kind == '商店' else used_gift
            remaining = max(0, goods['limit'] - used.get(week, 0))
            if kind == '商店':
                per = amounts(goods['rewards']).get(WOOD, 0)
                desired_wood = max(0, int(override.get('shop', p['weekly_shop_wood'])))
                # Without a daily override, apply the weekly budget once only.
                already = max(0, used.get(week, 0) - (goods['bought'] if week == week_key(today) else 0))
                count = min(remaining, max(0, desired_wood // per - already)) if per else 0
                shop_count = count
            else:
                reserved = sum(max(0, int(v.get('gifts', 0))) for k, v in (p.get('days') or {}).items()
                               if day.isoformat() < k <= end.isoformat())
                count = min(remaining, max(0, int(override['gifts']))) if 'gifts' in override else min(remaining, max(0, gifts_left - reserved))
                count = min(count, gifts_left)
                gifts_left -= count
                gift_count = count
            used[week] = used.get(week, 0) + count
            receive(kind, {k: v * count for k, v in amounts(goods['rewards']).items()})
            if kind == '商店' and goods.get('consume'):
                exchange_cost += int(goods['consume'][1]) * count
            if kind == '礼包':
                cash_cost += int(goods.get('price', 0)) * count
        if 'bp' in override and int(override['bp']) >= 0:
            wanted = min(bp_max, max(bp_level, int(override['bp'])))
            if wanted > bp_level:
                bp_level, bp_exp = wanted, 0
                day_events.append(f'按计划将战令设为{wanted}级（额外等级来源未计费用）')
        claim_pass()
        # Each row is the highest level supported by that day's materials.
        # A legacy preserve_daily setting must not restore a one-level/day cap.
        for _ in range(bp_max + maximum + 2):
            previous = (level, bp_level, bp_exp, len(earned))
            task_xp(sweeps, allow_daily)
            claim_pass()
            upgrade()
            if previous == (level, bp_level, bp_exp, len(earned)):
                break
        income = {name: totals[name].get(WOOD, 0) - before[name] for name in totals}
        rows.append({'date': day.isoformat(), 'stars': stars(), 'sweeps': sweeps,
                     'wood_each': amounts(sweep['rewards']).get(WOOD, 0),
                     'income': income, 'wood': resources.get(WOOD, 0), 'level': level,
                     'bp': bp_level, 'xp': bp_exp, 'earned_xp': day_xp,
                     'tickets': tickets,
                     'shop_count': shop_count, 'gift_count': gift_count, 'events': day_events})
        day += timedelta(days=1)
    if gifts_left:
        warnings.add(f'受每周限购和截止日限制，计划中有{gifts_left}个礼包尚未安排')
    if p['wood_only']:
        warnings.add('按木头测算：镇旗布、铜钱视为充足；材料缺口另列，达到日期以实际补齐为准')
    warnings.add('血月操作类任务按下一场尽早完成估算；充值经验按勾选计划或礼包金额计入')
    if not battles and any(t['metric'] == 'battles' and t['state'] < 2 for t in tasks):
        warnings.add('未读到未来血月场次，相关任务经验未计入，可在任务页设置完成日期')
    next_break = next((n for n in sorted(levels) if n > level and amounts(levels[n]['cost']).get(WOOD)), None)
    gap = max(0, sum(amounts(levels[n]['cost']).get(WOOD, 0) for n in levels if level < n <= next_break) - resources.get(WOOD, 0)) if next_break else 0
    return {'rows': rows, 'milestones': milestones, 'level': level, 'bp': bp_level,
            'resources': resources, 'income': totals, 'spent': spent,
            'initial': initial_resources, 'next_break': next_break, 'gap': gap,
            'diamond_cost': diamond_cost, 'exchange_cost': exchange_cost, 'cash_cost': cash_cost,
            'deficits': {k: -v for k, v in resources.items() if v < 0},
            'warnings': sorted(warnings), 'end': end.isoformat(),
            'earned_tasks': sorted({task for task, _ in earned})}
