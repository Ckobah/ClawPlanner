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
exports.CanceledEvent = void 0;
const typeorm_1 = require("typeorm");
let CanceledEvent = class CanceledEvent {
    id;
    cancelDate;
    eventId;
};
exports.CanceledEvent = CanceledEvent;
__decorate([
    (0, typeorm_1.PrimaryGeneratedColumn)(),
    __metadata("design:type", Number)
], CanceledEvent.prototype, "id", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'date', name: 'cancel_date' }),
    __metadata("design:type", String)
], CanceledEvent.prototype, "cancelDate", void 0);
__decorate([
    (0, typeorm_1.Column)({ type: 'int', name: 'event_id' }),
    __metadata("design:type", Number)
], CanceledEvent.prototype, "eventId", void 0);
exports.CanceledEvent = CanceledEvent = __decorate([
    (0, typeorm_1.Entity)({ name: 'canceled_events' })
], CanceledEvent);
//# sourceMappingURL=canceled-event.entity.js.map