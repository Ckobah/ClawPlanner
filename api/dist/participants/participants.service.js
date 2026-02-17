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
exports.ParticipantsService = void 0;
const common_1 = require("@nestjs/common");
const typeorm_1 = require("@nestjs/typeorm");
const typeorm_2 = require("typeorm");
const user_entity_1 = require("../entities/user.entity");
const user_relation_entity_1 = require("../entities/user-relation.entity");
let ParticipantsService = class ParticipantsService {
    users;
    relations;
    constructor(users, relations) {
        this.users = users;
        this.relations = relations;
    }
    async listParticipants(ownerTgId) {
        const owner = await this.users.findOne({ where: { tgId: String(ownerTgId) } });
        if (!owner) {
            return [];
        }
        const relations = await this.relations.find({ where: { userId: owner.id } });
        const relatedIds = relations.map((rel) => rel.relatedUserId);
        if (!relatedIds.length) {
            return [];
        }
        const relatedUsers = await this.users.find({ where: { id: (0, typeorm_2.In)(relatedIds) } });
        return relatedUsers.map((user) => ({
            tg_id: Number(user.tgId),
            first_name: user.firstName ?? '',
            is_active: user.isActive,
        }));
    }
    async deleteParticipants(ownerTgId, relatedTgIds) {
        const owner = await this.users.findOne({ where: { tgId: String(ownerTgId) } });
        if (!owner || !relatedTgIds.length) {
            return 0;
        }
        const relatedUsers = await this.users.find({ where: { tgId: (0, typeorm_2.In)(relatedTgIds.map(String)) } });
        if (!relatedUsers.length) {
            return 0;
        }
        const relatedIds = relatedUsers.map((user) => user.id);
        const result = await this.relations.delete({
            userId: owner.id,
            relatedUserId: (0, typeorm_2.In)(relatedIds),
        });
        return result.affected ?? 0;
    }
};
exports.ParticipantsService = ParticipantsService;
exports.ParticipantsService = ParticipantsService = __decorate([
    (0, common_1.Injectable)(),
    __param(0, (0, typeorm_1.InjectRepository)(user_entity_1.User)),
    __param(1, (0, typeorm_1.InjectRepository)(user_relation_entity_1.UserRelation)),
    __metadata("design:paramtypes", [typeorm_2.Repository,
        typeorm_2.Repository])
], ParticipantsService);
//# sourceMappingURL=participants.service.js.map