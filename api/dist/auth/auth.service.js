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
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.AuthService = void 0;
const common_1 = require("@nestjs/common");
const jwt_1 = require("@nestjs/jwt");
const config_1 = require("@nestjs/config");
const typeorm_1 = require("@nestjs/typeorm");
const crypto_1 = __importDefault(require("crypto"));
const typeorm_2 = require("typeorm");
const user_entity_1 = require("../entities/user.entity");
let AuthService = class AuthService {
    jwtService;
    config;
    users;
    constructor(jwtService, config, users) {
        this.jwtService = jwtService;
        this.config = config;
        this.users = users;
    }
    async telegramLogin(dto) {
        const token = this.config.get('TG_BOT_TOKEN');
        if (!token) {
            throw new common_1.UnauthorizedException('Bot token missing');
        }
        if (!this.verifyTelegramAuth(dto, token)) {
            throw new common_1.UnauthorizedException('Invalid Telegram signature');
        }
        const tgId = dto.id;
        const isAdmin = this.isAdmin(tgId);
        const tgIdString = String(tgId);
        let user = await this.users.findOne({ where: { tgId: tgIdString } });
        if (!user) {
            user = this.users.create({
                tgId: tgIdString,
                username: dto.username ?? null,
                firstName: dto.first_name ?? null,
                lastName: dto.last_name ?? null,
                isActive: true,
            });
        }
        else {
            user.username = dto.username ?? user.username ?? null;
            user.firstName = dto.first_name ?? user.firstName ?? null;
            user.lastName = dto.last_name ?? user.lastName ?? null;
            user.isActive = true;
        }
        await this.users.save(user);
        const payload = { tg_id: tgId, is_admin: isAdmin };
        const jwt = await this.jwtService.signAsync(payload);
        return { token: jwt };
    }
    async getMe(tgId) {
        return this.users.findOne({ where: { tgId: String(tgId) } });
    }
    isAdmin(tgId) {
        const raw = this.config.get('ADMIN_TG_IDS') ?? '';
        const admins = raw
            .split(',')
            .map((id) => id.trim())
            .filter(Boolean);
        return admins.includes(String(tgId));
    }
    verifyTelegramAuth(dto, botToken) {
        const data = {};
        Object.entries(dto).forEach(([key, value]) => {
            if (key === 'hash' || value === undefined || value === null) {
                return;
            }
            data[key] = String(value);
        });
        const dataCheckString = Object.keys(data)
            .sort()
            .map((key) => `${key}=${data[key]}`)
            .join('\n');
        const secretKey = crypto_1.default.createHash('sha256').update(botToken).digest();
        const hmac = crypto_1.default.createHmac('sha256', secretKey).update(dataCheckString).digest('hex');
        return hmac === dto.hash;
    }
};
exports.AuthService = AuthService;
exports.AuthService = AuthService = __decorate([
    (0, common_1.Injectable)(),
    __param(2, (0, typeorm_1.InjectRepository)(user_entity_1.User)),
    __metadata("design:paramtypes", [jwt_1.JwtService,
        config_1.ConfigService,
        typeorm_2.Repository])
], AuthService);
//# sourceMappingURL=auth.service.js.map