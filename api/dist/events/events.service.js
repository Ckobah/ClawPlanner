"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __metadata = (this && this.__metadata) || function (k, v) {
    if (typeof Reflect === "object" && typeof Reflect.metadata === "function") return Reflect.metadata(k, v);
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventsService = void 0;
const common_1 = require("@nestjs/common");
const typeorm_1 = require("@nestjs/typeorm");
const luxon_1 = require("luxon");
const typeorm_2 = require("typeorm");
const config_1 = require("@nestjs/config");
const canceled_event_entity_1 = require("../entities/canceled-event.entity");
const event_entity_1 = require("../entities/event.entity");
const user_entity_1 = require("../entities/user.entity");
let EventsService = class EventsService {
    config;
    events;
    users;
    canceled;
    constructor(config, events, users, canceled) {
        this.config = config;
        this.events = events;
        this.users = users;
        this.canceled = canceled;
    }
    async getMonth(userId, year, month) {
        const user = await this.getUser(userId);
        const tz = this.getUserTz(user);
        const monthStartLocal = luxon_1.DateTime.fromObject({ year, month, day: 1, hour: 0, minute: 0 }, { zone: tz });
        const monthEndLocal = monthStartLocal.endOf('month');
        const monthStartUtc = monthStartLocal.toUTC();
        const monthEndUtc = monthEndLocal.toUTC();
        const monthStartUtcMonth = monthStartUtc.month;
        const monthEndUtcMonth = monthEndUtc.month;
        const qb = this.events
            .createQueryBuilder('e')
            .where('e.tg_id = :tgId', { tgId: userId })
            .andWhere('e.start_at <= :monthEnd', { monthEnd: monthEndUtc.toJSDate() })
            .andWhere(`(
          (e.single_event = true AND e.start_at >= :monthStart)
          OR e.daily = true
          OR e.weekly IS NOT NULL
          OR e.monthly IS NOT NULL
          OR (e.annual_month IS NOT NULL AND e.annual_month IN (:...annualMonths))
        )`)
            .setParameter('monthStart', monthStartUtc.toJSDate())
            .setParameter('annualMonths', [monthStartUtcMonth, monthEndUtcMonth]);
        const events = await qb.getMany();
        if (!events.length) {
            return { days: this.initMonthDays(monthStartLocal.daysInMonth) };
        }
        const canceledMap = await this.getCanceledMap(events);
        const days = this.initMonthDays(monthStartLocal.daysInMonth);
        for (const event of events) {
            const startLocal = luxon_1.DateTime.fromJSDate(event.startAt, { zone: 'utc' }).setZone(tz);
            if (event.singleEvent) {
                days[startLocal.day] += 1;
                continue;
            }
            if (event.daily) {
                const startDay = startLocal.startOf('day');
                for (let day = 1; day <= monthStartLocal.daysInMonth; day += 1) {
                    const current = luxon_1.DateTime.fromObject({ year, month, day }, { zone: tz });
                    if (current < startDay) {
                        continue;
                    }
                    if (this.isCanceled(event.id, current, canceledMap)) {
                        continue;
                    }
                    days[day] += 1;
                }
                continue;
            }
            if (event.monthly !== null && event.monthly !== undefined) {
                const dayInMonth = Math.min(startLocal.day, monthStartLocal.daysInMonth);
                const current = luxon_1.DateTime.fromObject({ year, month, day: dayInMonth }, { zone: tz });
                if (current >= startLocal.startOf('day') && !this.isCanceled(event.id, current, canceledMap)) {
                    days[dayInMonth] += 1;
                }
                continue;
            }
            if (event.annualDay && event.annualMonth) {
                if (event.annualMonth !== month) {
                    continue;
                }
                const current = luxon_1.DateTime.fromObject({ year, month, day: event.annualDay }, { zone: tz });
                if (current >= startLocal.startOf('day') && !this.isCanceled(event.id, current, canceledMap)) {
                    days[event.annualDay] += 1;
                }
                continue;
            }
            if (event.weekly !== null && event.weekly !== undefined) {
                const targetWeekday = event.weekly;
                for (let day = 1; day <= monthStartLocal.daysInMonth; day += 1) {
                    const current = luxon_1.DateTime.fromObject({ year, month, day }, { zone: tz });
                    if (this.weekdayToDb(current.weekday) !== targetWeekday) {
                        continue;
                    }
                    if (current < startLocal.startOf('day')) {
                        continue;
                    }
                    if (this.isCanceled(event.id, current, canceledMap)) {
                        continue;
                    }
                    days[day] += 1;
                }
            }
        }
        return { days };
    }
    async getDay(userId, year, month, day) {
        const user = await this.getUser(userId);
        const tz = this.getUserTz(user);
        const dayStartLocal = luxon_1.DateTime.fromObject({ year, month, day, hour: 0, minute: 0 }, { zone: tz });
        const dayEndLocal = dayStartLocal.endOf('day');
        const dayStartUtc = dayStartLocal.toUTC();
        const dayEndUtc = dayEndLocal.toUTC();
        const addDays = day === dayStartLocal.daysInMonth ? 4 : 0;
        const dayStartForMonthly = dayStartUtc.day > dayEndUtc.day ? 1 : dayStartUtc.day;
        const qb = this.events
            .createQueryBuilder('e')
            .where('e.tg_id = :tgId', { tgId: userId })
            .andWhere('e.start_at <= :dayEnd', { dayEnd: dayEndUtc.toJSDate() })
            .andWhere(`(
          (e.single_event = true AND e.start_at >= :dayStart)
          OR e.daily = true
          OR (e.weekly IS NOT NULL AND e.weekly IN (:...weekdays))
          OR (e.monthly IS NOT NULL AND (e.monthly IN (:...monthDays) OR e.monthly = :dayStartDay))
          OR (e.annual_day IS NOT NULL AND e.annual_day IN (:...annualDays) AND e.annual_month IN (:...annualMonths))
        )`)
            .setParameter('dayStart', dayStartUtc.toJSDate())
            .setParameter('weekdays', [dayStartUtc.weekday - 1, dayEndUtc.weekday - 1])
            .setParameter('monthDays', this.range(dayStartForMonthly, dayEndUtc.day + addDays))
            .setParameter('dayStartDay', dayStartUtc.day)
            .setParameter('annualDays', [dayStartUtc.day, dayEndUtc.day])
            .setParameter('annualMonths', [dayStartUtc.month, dayEndUtc.month]);
        const events = await qb.getMany();
        if (!events.length) {
            return [];
        }
        const canceledMap = await this.getCanceledMap(events);
        const results = [];
        for (const event of events) {
            const startLocal = luxon_1.DateTime.fromJSDate(event.startAt, { zone: 'utc' }).setZone(tz);
            const stopLocal = event.stopAt ? luxon_1.DateTime.fromJSDate(event.stopAt, { zone: 'utc' }).setZone(tz) : null;
            const dateLocal = luxon_1.DateTime.fromObject({ year, month, day }, { zone: tz });
            if (this.isCanceled(event.id, dateLocal, canceledMap)) {
                continue;
            }
            let recurrentLabel = '';
            if (event.daily) {
                recurrentLabel = 'daily';
            }
            else if (event.weekly !== null && event.weekly !== undefined) {
                if (event.weekly !== this.weekdayToDb(dayStartLocal.weekday)) {
                    continue;
                }
                recurrentLabel = 'weekly';
            }
            else if (event.monthly !== null && event.monthly !== undefined) {
                if (startLocal.day < dayStartLocal.day || startLocal.day > dayStartLocal.day + addDays) {
                    continue;
                }
                recurrentLabel = 'monthly';
            }
            else if (event.annualDay && event.annualMonth) {
                if (startLocal.day !== dayStartLocal.day || startLocal.month !== dayStartLocal.month) {
                    continue;
                }
                recurrentLabel = 'annual';
            }
            results.push({
                id: event.id,
                description: event.description,
                start_time: startLocal.toFormat('HH:mm'),
                stop_time: stopLocal ? stopLocal.toFormat('HH:mm') : null,
                recurrent: recurrentLabel,
                single_event: !!event.singleEvent,
            });
        }
        results.sort((a, b) => a.start_time.localeCompare(b.start_time));
        return results;
    }
    async createEvent(userId, dto) {
        const user = await this.getUser(userId);
        const tz = this.getUserTz(user);
        const startLocal = luxon_1.DateTime.fromISO(`${dto.date}T${dto.start_time}`, { zone: tz });
        const startUtc = startLocal.toUTC();
        const stopUtc = dto.stop_time
            ? luxon_1.DateTime.fromISO(`${dto.date}T${dto.stop_time}`, { zone: tz }).toUTC()
            : null;
        const event = this.events.create({
            description: dto.description,
            startTime: startUtc.toFormat('HH:mm:ss'),
            startAt: startUtc.toJSDate(),
            stopAt: stopUtc ? stopUtc.toJSDate() : null,
            singleEvent: dto.recurrent === 'never',
            daily: dto.recurrent === 'daily' ? true : null,
            weekly: dto.recurrent === 'weekly' ? this.weekdayToDb(startUtc.weekday) : null,
            monthly: dto.recurrent === 'monthly' ? startUtc.day : null,
            annualDay: dto.recurrent === 'annual' ? startUtc.day : null,
            annualMonth: dto.recurrent === 'annual' ? startUtc.month : null,
            tgId: userId,
        });
        const saved = await this.events.save(event);
        if (dto.participants?.length) {
            await this.copyToParticipants(saved, dto.participants);
        }
        return { id: saved.id };
    }
    async deleteEvent(userId, eventId, date) {
        const event = await this.events.findOne({ where: { id: eventId, tgId: userId } });
        if (!event) {
            throw new common_1.NotFoundException('Event not found');
        }
        if (!event.singleEvent && date) {
            await this.canceled.save({
                cancelDate: date,
                eventId: event.id,
            });
            return { canceled: true };
        }
        await this.events.delete({ id: event.id });
        return { deleted: true };
    }
    async copyToParticipants(event, participantTgIds) {
        for (const tgId of participantTgIds) {
            const copy = this.events.create({
                description: event.description,
                startTime: event.startTime,
                startAt: event.startAt,
                stopAt: event.stopAt,
                singleEvent: event.singleEvent,
                daily: event.daily,
                weekly: event.weekly,
                monthly: event.monthly,
                annualDay: event.annualDay,
                annualMonth: event.annualMonth,
                tgId,
            });
            await this.events.save(copy);
        }
    }
    async getUser(tgId) {
        const user = await this.users.findOne({ where: { tgId: String(tgId) } });
        if (!user) {
            throw new common_1.NotFoundException('User not found');
        }
        return user;
    }
    getUserTz(user) {
        return user.timeZone ?? this.config.get('DEFAULT_TIMEZONE_NAME') ?? 'Europe/Moscow';
    }
    async getCanceledMap(events) {
        const ids = events.map((e) => e.id);
        const cancels = await this.canceled.find({ where: { eventId: (0, typeorm_2.In)(ids) } });
        const map = new Map();
        for (const cancel of cancels) {
            if (!map.has(cancel.eventId)) {
                map.set(cancel.eventId, new Set());
            }
            map.get(cancel.eventId)?.add(cancel.cancelDate);
        }
        return map;
    }
    isCanceled(eventId, date, canceledMap) {
        const set = canceledMap.get(eventId);
        if (!set) {
            return false;
        }
        return set.has(date.toISODate() ?? '');
    }
    initMonthDays(numDays) {
        const days = {};
        for (let day = 1; day <= numDays; day += 1) {
            days[day] = 0;
        }
        return days;
    }
    range(start, end) {
        const result = [];
        for (let value = start; value <= end; value += 1) {
            result.push(value);
        }
        return result;
    }
    weekdayToDb(weekday) {
        return (weekday + 6) % 7;
    }
};
exports.EventsService = EventsService;
exports.EventsService = EventsService = __decorate([
    (0, common_1.Injectable)(),
    __param(1, (0, typeorm_1.InjectRepository)(event_entity_1.Event)),
    __param(2, (0, typeorm_1.InjectRepository)(user_entity_1.User)),
    __param(3, (0, typeorm_1.InjectRepository)(canceled_event_entity_1.CanceledEvent)),
    __metadata("design:paramtypes", [config_1.ConfigService,
        typeorm_2.Repository,
        typeorm_2.Repository,
        typeorm_2.Repository])
], EventsService);
//# sourceMappingURL=events.service.js.map