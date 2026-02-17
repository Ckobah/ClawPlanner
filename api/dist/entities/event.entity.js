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
Object.defineProperty(exports, "__esModule", { value: true });
exports.Event = void 0;
const typeorm_1 = require("typeorm");
let Event = class Event {
    id;
    description;
    startTime;
    startAt;
    stopAt;
    singleEvent;
    daily;
    weekly;
    monthly;
    annualDay;
    annualMonth;
    tgId;
    createdAt;
};
exports.Event = Event;
__decorate([
    (0, typeorm_1.PrimaryGeneratedColumn)(),
    __metadata("design:type", Number)
], Event.prototype, "id", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'varchar' }),
    __metadata("design:type", String)
], Event.prototype, "description", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'time', name: 'start_time' }),
    __metadata("design:type", String)
], Event.prototype, "startTime", void 0);
__decorate([
    (0, typeorm_1.Index)(),
    (0, typeorm_1.Column)({ type: 'timestamptz', name: 'start_at' }),
    __metadata("design:type", Date)
], Event.prototype, "startAt", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'timestamptz', name: 'stop_at', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "stopAt", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'boolean', name: 'single_event', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "singleEvent", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'boolean', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "daily", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'int', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "weekly", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'int', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "monthly", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'int', name: 'annual_day', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "annualDay", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'int', name: 'annual_month', nullable: true }),
    __metadata("design:type", Object)
], Event.prototype, "annualMonth", void 0);
__decorate([
    (0, typeorm_1.Index)(),
    (0, typeorm_1.Column)({ type: 'int', name: 'tg_id' }),
    __metadata("design:type", Number)
], Event.prototype, "tgId", void 0);
__decorate([
    (0, typeorm_1.CreateDateColumn)({ type: 'timestamptz', name: 'created_at' }),
    __metadata("design:type", Date)
], Event.prototype, "createdAt", void 0);
exports.Event = Event = __decorate([
    (0, typeorm_1.Entity)({ name: 'events' })
], Event);
//# sourceMappingURL=event.entity.js.map