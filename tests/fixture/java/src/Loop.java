public class Loop {
    public static void main(String[] args) throws InterruptedException {
        for (int i = 0; ; i++) {
            System.out.println("tick " + i);
            Thread.sleep(500);
        }
    }
}
