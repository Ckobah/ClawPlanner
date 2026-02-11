"use strict";
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventsModule = void 0;
const common_1 = require("@nestjs/common");
const typeorm_1 = require("@nestjs/typeorm");
const canceled_event_entity_1 = require("../entities/canceled-event.entity");
const event_entity_1 = require("../entities/event.entity");
const user_entity_1 = require("../entities/user.entity");
const auth_module_1 = require("../auth/auth.module");
const events_controller_1 = require("./events.controller");
const events_service_1 = require("./events.service");
let EventsModule = class EventsModule {
};
exports.EventsModule = EventsModule;
exports.EventsModule = EventsModule = __decorate([
    (0, common_1.Module)({
        imports: [typeorm_1.TypeOrmModule.forFeature([event_entity_1.Event, user_entity_1.User, canceled_event_entity_1.CanceledEvent]), auth_module_1.AuthModule],
        controllers: [events_controller_1.EventsController],
        providers: [events_service_1.EventsService],
    })
], EventsModule);
//# sourceMappingURL=events.module.js.map