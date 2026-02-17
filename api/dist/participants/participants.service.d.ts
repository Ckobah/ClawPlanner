import { Repository } from 'typeorm';
import { User } from '../entities/user.entity';
import { UserRelation } from '../entities/user-relation.entity';
export declare class ParticipantsService {
    private readonly users;
    private readonly relations;
    constructor(users: Repository<User>, relations: Repository<UserRelation>);
    listParticipants(ownerTgId: number): Promise<{
        tg_id: number;
        first_name: string;
        is_active: boolean;
    }[]>;
    deleteParticipants(ownerTgId: number, relatedTgIds: number[]): Promise<number>;
}
