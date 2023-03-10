from machine import Pin
from rp2 import PIO, StateMachine, asm_pio
from micropython import const
from array import array
from uctypes import addressof
from gc import mem_free,collect




OVCLK=False     


@micropython.viper
def set_freq(fclock:int)->int:
    #clock frequency to run the pico default 125MHz. Allow 100-250
    if (fclock<100000000 or fclock>250000000):
        print("invalid clock speed",fclock)
        print("Clock speed must be set between 100MHz and 250MHz")
        return
    if fclock<=130000000:
        FBDIV=fclock//1000000
        POSTDIV1=6  #default 6
        POSTDIV2=2  #default 2
    else: 
        FBDIV=fclock//2000000
        POSTDIV1=3  #default 6
        POSTDIV2=2  #default 2
    ptr32(0x4002800c)[0] = (POSTDIV1<<16)|(POSTDIV2<<12)
    ptr32(0x40028008)[0] = FBDIV
    cs=FBDIV*12//(POSTDIV1*POSTDIV2)
    print('clock speed',cs,'MHz')


H_res=const(640)            
V_res=const(480)            
bit_per_pix=const(3)        
pixel_bitmask=const(0b111)   
usable_bits=const(30)       
pix_per_words=const(10)   

if OVCLK:
    set_freq(250000000)
    SM0_FREQ=12587500  
    SM1_FREQ=125000000 
    SM2_FREQ=113287500 
else:
    SM0_FREQ=25175000 
    SM1_FREQ=125000000
    SM2_FREQ=100700000 



@asm_pio(set_init=PIO.OUT_HIGH, autopull=True, pull_thresh=32)
def paral_Hsync():
    wrap_target()
    # ACTIVE + FRONTPORCH
    mov(x, osr)              
    label("activeporch")
    jmp(x_dec,"activeporch")  
    # SYNC PULSE
    set(pins, 0) [31]    
    set(pins, 0) [31]    
    set(pins, 0) [31]    
    # BACKPORCH
    set(pins, 1) [31]    
    set(pins, 1) [13]    
    irq(0)             
    wrap()
#     
paral_write_Hsync = StateMachine(0, paral_Hsync,freq=SM0_FREQ, set_base=Pin(4))
# #

@asm_pio(sideset_init=(PIO.OUT_HIGH,) * 1, autopull=True, pull_thresh=32)
def paral_Vsync():
    pull(block)                 
    wrap_target()
    # ACTIVE
    mov(x, osr)                      
    label("active")
    wait(1,irq,0)                    
    irq(1)                            
    jmp(x_dec,"active")                
    # FRONTPORCH
    set(y, 9)                        
    label("frontporch")
    wait(1,irq,0)                   
    jmp(y_dec,"frontporch")           
    # SYNC PULSE
    wait(1,irq,0)              .side(0)
    wait(1,irq,0)                      
    # BACKPORCH
    set(y, 31)                        
    label("backporch")
    wait(1,irq,0)              .side(1) 
    jmp(y_dec,"backporch")             
    wait(1,irq,0)
    wrap()
# 
paral_write_Vsync = StateMachine(1, paral_Vsync,freq=SM1_FREQ, sideset_base=Pin(5))


@asm_pio(out_init=(PIO.OUT_LOW,) * 3, out_shiftdir=PIO.SHIFT_RIGHT, sideset_init=(PIO.OUT_LOW,) * 3, autopull=True, pull_thresh=usable_bits)
def paral_RGB():
    pull(block)                  
    mov(y, osr)                 
    wrap_target()
    mov(x, y)                  .side(0) 
    wait(1,irq,1)              
    label("colorout")
    out(pins,3)               
    nop()                 
            
    jmp(x_dec,"colorout")      
    wrap()                   
    
paral_write_RGB = StateMachine(2, paral_RGB,freq=SM2_FREQ, out_base=Pin(0),sideset_base=Pin(0))

@micropython.viper
def configure_DMAs(nword:int, H_buffer_line_add:ptr32):
   
   
    IRQ_QUIET = 0  
    RING_SEL = 0  
    RING_SIZE = 0 
    HIGH_PRIORITY = 1
    INCR_WRITE = 0  

   
    TREQ_SEL = 2   
    INCR_READ = 1  
    DATA_SIZE = 2  
    CHAIN_TO = 0   
    EN = 1          
    DMA_control_word = ((IRQ_QUIET << 21) | (TREQ_SEL << 15) | (CHAIN_TO  << 11) | (RING_SEL << 10) |
                        (RING_SIZE << 9) | (INCR_WRITE << 5) | (INCR_READ << 4) | (DATA_SIZE << 2) |
                        (HIGH_PRIORITY << 1) | (EN << 0))
    ptr32(0x50000040)[0] = 0                       
    ptr32(0x50000044)[0] = uint(0x50200018)         
    ptr32(0x50000048)[0] = nword                    
    ptr32(0x50000060)[0] = DMA_control_word         
    
    TREQ_SEL = 0x3f
    INCR_READ = 0   
    CHAIN_TO = 0   
    EN = 1          
    DMA_control_word = ((IRQ_QUIET << 21) | (TREQ_SEL << 15) | (CHAIN_TO  << 11) | (RING_SEL << 10) |
                        (RING_SIZE << 9) | (INCR_WRITE << 5) | (INCR_READ << 4) | (DATA_SIZE << 2) |
                        (HIGH_PRIORITY << 1) | (EN << 0))
    ptr32(0x50000000)[0] = uint(H_buffer_line_add)       
    ptr32(0x50000004)[0] = uint(0x5000007c)            
    ptr32(0x50000008)[0] = 1                             
    ptr32(0x50000010)[0] = DMA_control_word             
@micropython.viper
def startsync():
    V=int(ptr16(V_res))
    H=int(ptr16(H_res))
    paral_write_Hsync.put(655)      
    paral_write_Vsync.put(int(V-1)) 
    paral_write_RGB.put(int(H-1))   
    ptr32(0x50000430)[0] |= 0b00001 
    ptr32(0x50200000)[0] |= 0b111   

    
   
@micropython.viper
def stopsync():
    ptr32(0x50000444)[0] |= 0b000011        
    ptr32(0x50200000)[0] &= 0b111111111000  
    

@micropython.viper
def draw_pix(x:int,y:int,col:int):
    Data=ptr32(H_buffer_line)
    n=int((y)*(int(H_res)*int(bit_per_pix))+ (x)*int(bit_per_pix))
    k=(n//int(usable_bits)-1) if (n//int(usable_bits)>0)  else (int(len(H_buffer_line))-1)
    p=n%int(usable_bits)
    mask= ((int(pixel_bitmask) << p)^0x3FFFFFFF)
    Data[k]=(Data[k] & mask) | (col << p)

@micropython.viper
def fill_screen(col:int):
    Data=ptr32(H_buffer_line)
    mask=0
    for i in range(0,int(pix_per_words)):
        mask|=col<<(int(bit_per_pix)*i)
    i=0
    while i < int(len(H_buffer_line)):
        Data[i]=mask
        i+=1
    

@micropython.viper
def draw_fastHline(x1:int,x2:int,y:int,col:int):
    if (x1<0):x1=0
    if (x1>(int(H_res)-1)):x1=(int(H_res)-1)
    if (x2<0):x2=0
    if (x2>(int(H_res)-1)):x2=(int(H_res)-1)
    if (y<0):y=0
    if (y>(int(V_res)-1)):y=(int(V_res)-1)
    if (x2<x1):
        temp = x1
        x1 = x2
        x2 = temp
    Data=ptr32(H_buffer_line)
    n1=int((y)*(int(H_res)*int(bit_per_pix))+ (x1)*int(bit_per_pix))
    n2=int((y)*(int(H_res)*int(bit_per_pix))+ (x2)*int(bit_per_pix))
    k1=(n1//int(usable_bits)-1) if (n1//int(usable_bits)>0)  else (int(len(H_buffer_line))-1)
    k2=(n2//int(usable_bits)-1) if (n2//int(usable_bits)>0)  else (int(len(H_buffer_line))-1)
    if (k2==k1):
        for i in range(x1,x2):
            draw_pix(i,y,col)
        return
    p1=n1%int(usable_bits)
    p2=n2%int(usable_bits)
    mask1off=0
    mask1col=0
    mask2off=0
    mask2col=0
    for i in range(p1//int(bit_per_pix),int(pix_per_words)):
        mask1off|=(int(pixel_bitmask))<<(int(bit_per_pix)*i)
        mask1col|=col<<(int(bit_per_pix)*i)
    mask1off^=int(0x3FFFFFFF)
    for i in range(0,p2//int(bit_per_pix)):
        mask2off|=(int(pixel_bitmask))<<(int(bit_per_pix)*i)
        mask2col|=col<<(int(bit_per_pix)*i)
    mask2off^=0x3FFFFFFF
    Data[k1]=(Data[k1] & mask1off) | mask1col
    Data[k2]=(Data[k2] & mask2off) | mask2col
    mask=0
    for i in range(0,int(pix_per_words)):
        mask|=col<<(int(bit_per_pix)*i)
    i=k1+1
    if (i>(int(len(H_buffer_line))-1)):i=0
    while i < k2:
        Data[i]=mask
        i+=1
    
@micropython.viper
def draw_fastVline(x:int,y1:int,y2:int,col:int):
    if (x<0):x=0
    if (x>(int(H_res)-1)):x=(int(H_res)-1)
    if (y1<0):y1=0
    if (y1>(int(V_res)-1)):y1=(int(V_res)-1)
    if (y2<0):y2=0
    if (y2>(int(V_res)-1)):y2=(int(V_res)-1)
    if (y2<y1):
        temp = y1
        y1 = y2
        y2 = temp
    Data=ptr32(H_buffer_line)
    n1=int((y1)*(int(H_res)*int(bit_per_pix))+ (x)*int(bit_per_pix))
    k1=(n1//int(usable_bits)-1) if (n1//int(usable_bits)>0)  else (int(len(H_buffer_line))-1)
    p1=n1%int(usable_bits)
    nword=(int(len(H_buffer_line))//int(V_res))
    mask= ((int(pixel_bitmask) << p1)^0x3FFFFFFF)
    for i in range(y2-y1):
        Data[k1+i*nword]=(Data[k1+i*nword] & mask) | (col << p1)

@micropython.viper
def fill_rect(x1:int,y1:int,x2:int,y2:int,col:int):
    j=int(min(y1,y2))
    while (j<int(max(y1,y2))):
        draw_fastHline(x1,x2,j,col)
        j+=1

@micropython.viper
def draw_rect(x1:int,y1:int,x2:int,y2:int,col:int):
    draw_fastHline(x1,x2,y1,col)
    draw_fastHline(x1,x2,y2,col)
    draw_fastVline(x1,y1,y2,col)
    draw_fastVline(x2,y1,y2,col)

@micropython.viper
def draw_circle(x:int, y:int, r:int , color:int):
    if (x < 0 or y < 0 or x >= int(H_res) or y >= int(V_res)):
        return
    # Bresenham algorithm
    x_pos = 0-r
    y_pos = 0
    err = 2 - 2 * r
    while 1:
        draw_pix(x-x_pos, y+y_pos,color)
        draw_pix(x-x_pos, y-y_pos,color)
        draw_pix(x+x_pos, y+y_pos,color)
        draw_pix(x+x_pos, y-y_pos,color)
        e2 = err
        if (e2 <= y_pos):
            y_pos += 1
            err += y_pos * 2 + 1
            if((0-x_pos) == y_pos and e2 <= x_pos):
                e2 = 0
        if (e2 > x_pos):
            x_pos += 1
            err += x_pos * 2 + 1
        if x_pos > 0:
            break

@micropython.viper
def fill_disk(x:int, y:int, r:int , color:int):
    if (x < 0 or y < 0 or x >= int(H_res) or y >= int(V_res)):
        return
    # Bresenham algorithm
    x_pos = 0-r
    y_pos = 0
    err = 2 - 2 * r
    while 1:
        draw_fastHline(x-x_pos,x+x_pos,y+y_pos,color)
        draw_fastHline(x-x_pos,x+x_pos,y-y_pos,color)
        e2 = err
        if (e2 <= y_pos):
            y_pos += 1
            err += y_pos * 2 + 1
            if((0-x_pos) == y_pos and e2 <= x_pos):
                e2 = 0
        if (e2 > x_pos):
            x_pos += 1
            err += x_pos * 2 + 1
        if x_pos > 0:
            break


# Builfing the Data array buffer
collect()
a0=mem_free()
# Initiate the buffer - an array of consecutive 32bit words containing ALL the visible pixels
H_buffer_line = array('L')
# Number of required 32bit words
visible_pix=int((H_res)*V_res*bit_per_pix/usable_bits)
# Creating an array with all the 32b words set to zero
for k in range(visible_pix):
    H_buffer_line.append(0)
# We need an array containing the adress of the buffer for the DMA chan0 to read the values
H_buffer_line_address=array('L',[addressof(H_buffer_line)])
# a few information on what we just built
a1=mem_free()
print("mem used by buffer array (kB):\t"+str(round((a0-a1)/1024,3)))
print("Number of 32b words:\t\t"+str(visible_pix))
print("Number of bits (total):\t\t"+str(32*visible_pix))
print("Number of bits (usable):\t"+str(usable_bits*visible_pix))
collect()
a0=mem_free()
print("\nremaining RAM (kB):\t"+str(round(a0/1024,3)))


# 3 bit color names
RED     = 0b001
GREEN   = 0b010
BLUE    = 0b100
YELLOW  = 0b011
BLACK   = 0
WHITE   = 0b111
CYAN    = 0b110
MAGENTA = 0b101

# Configure the DMAs
configure_DMAs(len(H_buffer_line),H_buffer_line_address)
# Start the PIO Statemchines and the DMA Channels
startsync()

# Drawing a simple 8 color checker
for h in range(8):
    for i in range(0,60):
        for k in range(8):
            col=(h+k)%8
            draw_fastHline(k*80,k*80+80,h*60+i,col)


# Drawing Various figures
fill_rect(20,20,150,150,BLACK)
fill_rect(20,200,150,400,BLUE)
fill_rect(200,205,205,150,WHITE)
fill_rect(300,415,350,300,YELLOW)
fill_rect(550,450,640,150,CYAN)
draw_circle(100,400,75,YELLOW)
draw_circle(150,150,98,CYAN)
fill_disk(320,240,150,BLACK)
fill_disk(320,240,120,RED)
fill_disk(320,240,80,GREEN)
fill_disk(320,240,50,WHITE)
draw_rect(500,50,620,70,BLACK)
draw_rect(100,390,600,480,RED)
