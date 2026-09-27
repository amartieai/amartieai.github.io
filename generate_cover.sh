#!/bin/bash
# Generate oracle cover video with proper text overlays
# Uses existing video as base, overlays clean text

ffmpeg -y -i /home/atlas/ORACLE_NEW/business/static/video/oracle_cover.mp4 \
  -filter_complex "
    [0:v]drawtext=text='EVENT ALERT':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf:fontsize=36:fontcolor=0xe8b86d:x=(w-text_w)/2:y=180:enable='between(t,3,7)',
    drawtext=text='WINDOW 14:00   SENT 13:59:12':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf:fontsize=22:fontcolor=0xe8b86d:x=(w-text_w)/2:y=240:enable='between(t,3,7)',
    drawtext=text='WE KNOW THE WHEN.':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf:fontsize=56:fontcolor=0xe8b86d:x=(w-text_w)/2:y=380:enable='between(t,12,15)',
    drawtext=text='YOU DO THE REST.':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf:fontsize=56:fontcolor=0xe8b86d:x=(w-text_w)/2:y=470:enable='between(t,12,15)',
    drawtext=text='amartie.com':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf:fontsize=18:fontcolor=0xe8b86d:x=(w-text_w)/2:y=600:enable='between(t,13,15)'
  " \
  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  -t 15 -movflags +faststart \
  /home/atlas/ORACLE_NEW/business/static/video/oracle_cover_fixed.mp4
