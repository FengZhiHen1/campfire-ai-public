import {Config} from '@remotion/cli/config';

// 预览与终稿统一走 JPEG 帧 + H.264（腾讯 LIGHT 提交格式：1920×1080@30fps）
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
