#!/usr/bin/env python3
"""
Generate PWA icons for Revo Fitness app
Creates PNG icons in various sizes from an SVG template
"""

import os
from pathlib import Path

def create_svg_icon():
    """Create a simple SVG icon for Revo Fitness"""
    return '''<svg width="512" height="512" viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">
  <!-- Background circle -->
  <circle cx="256" cy="256" r="240" fill="#007bff" stroke="#0056b3" stroke-width="8"/>
  
  <!-- Dumbbell icon -->
  <g fill="white" stroke="white" stroke-width="2">
    <!-- Left weight -->
    <rect x="80" y="220" width="40" height="72" rx="8"/>
    <!-- Left handle -->
    <rect x="120" y="240" width="60" height="32" rx="4"/>
    <!-- Center bar -->
    <rect x="180" y="248" width="152" height="16" rx="8"/>
    <!-- Right handle -->
    <rect x="332" y="240" width="60" height="32" rx="4"/>
    <!-- Right weight -->
    <rect x="392" y="220" width="40" height="72" rx="8"/>
  </g>
  
  <!-- Pulse/live indicator -->
  <circle cx="420" cy="120" r="20" fill="#28a745">
    <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="420" cy="120" r="12" fill="white"/>
  
  <!-- App title -->
  <text x="256" y="420" font-family="Arial, sans-serif" font-size="36" font-weight="bold" 
        text-anchor="middle" fill="white">REVO</text>
  <text x="256" y="455" font-family="Arial, sans-serif" font-size="20" 
        text-anchor="middle" fill="#e6f3ff">LIVE COUNT</text>
</svg>'''

def generate_icons():
    """Generate PNG icons from SVG using online conversion or placeholder method"""
    
    # Create static directory if it doesn't exist
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    
    # Icon sizes needed for PWA
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    
    svg_content = create_svg_icon()
    
    # Save SVG file
    svg_path = static_dir / "icon.svg"
    with open(svg_path, 'w') as f:
        f.write(svg_content)
    
    print(f"✅ Created SVG icon: {svg_path}")
    
    # For now, create a simple HTML file that shows how to convert
    # In a real deployment, you'd use a tool like cairosvg, Pillow, or an online service
    
    conversion_html = f'''<!DOCTYPE html>
<html>
<head>
    <title>PWA Icon Converter</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; }}
        .icon-preview {{ text-align: center; margin: 20px 0; }}
        .size-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 20px; }}
        .size-item {{ text-align: center; padding: 10px; border: 1px solid #ddd; border-radius: 8px; }}
        .instructions {{ background: #f0f8ff; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
    </style>
</head>
<body>
    <h1>🎨 Revo Fitness PWA Icons</h1>
    
    <div class="icon-preview">
        <h2>Source SVG Icon</h2>
        <div style="width: 128px; height: 128px; margin: 0 auto; border: 1px solid #ddd; display: flex; align-items: center; justify-content: center; background: #f9f9f9;">
            <em>SVG icon created at: {svg_path}</em>
        </div>
    </div>
    
    <div class="instructions">
        <h3>📋 Next Steps - Generate PNG Icons</h3>
        <p>To complete the PWA setup, convert the SVG to PNG files in these sizes:</p>
        <div class="size-grid">
            {' '.join(f'<div class="size-item"><strong>{size}x{size}</strong><br>icon-{size}x{size}.png</div>' for size in sizes)}
        </div>
        
        <h4>Option 1: Online Converter</h4>
        <ol>
            <li>Visit <a href="https://convertio.co/svg-png/" target="_blank">convertio.co/svg-png/</a></li>
            <li>Upload the SVG file: <code>{svg_path}</code></li>
            <li>Set each target size and download the PNG files</li>
            <li>Save them as: <code>icon-72x72.png</code>, <code>icon-96x96.png</code>, etc.</li>
        </ol>
        
        <h4>Option 2: Command Line (if you have ImageMagick)</h4>
        <pre><code># Install ImageMagick first, then run:
{chr(10).join(f'convert icon.svg -resize {size}x{size} icon-{size}x{size}.png' for size in sizes)}</code></pre>
        
        <h4>Option 3: Python with cairosvg (recommended)</h4>
        <pre><code>pip install cairosvg Pillow
python -c "
import cairosvg
from PIL import Image
import io

svg_path = '{svg_path}'
sizes = {sizes}

for size in sizes:
    # Convert SVG to PNG
    png_data = cairosvg.svg2png(url=svg_path, output_width=size, output_height=size)
    
    # Save PNG file
    with open(f'static/icon-{{size}}x{{size}}.png', 'wb') as f:
        f.write(png_data)
    
    print(f'✅ Created icon-{{size}}x{{size}}.png')
"</code></pre>
    </div>
    
    <div class="instructions">
        <h3>🖼️ Screenshots (Optional)</h3>
        <p>For better app store presentation, create these screenshots:</p>
        <ul>
            <li><code>screenshot-mobile.png</code> - 390x844 (mobile view)</li>
            <li><code>screenshot-desktop.png</code> - 1280x720 (desktop view)</li>
        </ul>
    </div>
    
    <p><em>Once icons are generated, your PWA will be ready to install on mobile devices!</em></p>
</body>
</html>'''
    
    instruction_path = static_dir / "generate_icons.html"
    with open(instruction_path, 'w') as f:
        f.write(conversion_html)
    
    print(f"📋 Created icon generation guide: {instruction_path}")
    print(f"🌐 Open in browser: file://{instruction_path.absolute()}")

if __name__ == "__main__":
    generate_icons()