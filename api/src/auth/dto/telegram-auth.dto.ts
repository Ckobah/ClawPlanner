import { Type } from 'class-transformer';
import { IsInt, IsOptional, IsString } from 'class-validator';

export class TelegramAuthDto {
  @IsInt()
  @Type(() => Number)
  id!: number;

  @IsString()
  hash!: string;

  @IsInt()
  @Type(() => Number)
  auth_date!: number;

  @IsOptional()
  @IsString()
  first_name?: string;

  @IsOptional()
  @IsString()
  last_name?: string;

  @IsOptional()
  @IsString()
  username?: string;

  @IsOptional()
  @IsString()
  photo_url?: string;
}
